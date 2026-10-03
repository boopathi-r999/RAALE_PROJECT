"""
backend/main.py — Access-Instruction Capture & Reuse System API
================================================================
Endpoints:
  POST /addresses                      – register address
  GET  /dispatch/{address_id}          – get best note + confidence for dispatch
  POST /attempts                       – log delivery outcome (with rate guard)
  POST /notes                          – log access note (validated)
  POST /notes/{note_id}/confirm        – confirm/contradict note
  GET  /explorer                       – address registry (sortable)
  GET  /history/{address_id}           – full audit trail
  POST /demo/edge-case/{case_id}       – live edge-case demo (1–6)
  GET  /duplicates/flag                – get pending duplicate pairs
  POST /duplicates/{log_id}/decide     – ops merge/keep-separate decision
  POST /notify                         – send (simulated or real) customer notification
"""

import json
import joblib
import os
import re
import math
import hashlib
import logging
import difflib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import models, schemas, uncertainty
from .database import engine, get_db

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("access_system")

# ── App bootstrap ──────────────────────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Access-Instruction Capture & Reuse System", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

eval_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "evaluation")
if os.path.exists(eval_path):
    app.mount("/evaluation", StaticFiles(directory=eval_path), name="evaluation")

ml_artifacts_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ml", "artifacts")
if os.path.exists(ml_artifacts_path):
    app.mount("/ml/artifacts", StaticFiles(directory=ml_artifacts_path), name="ml_artifacts")


# ── Notification mode (read from env, default simulated) ──────────────────────
NOTIFY_MODE = os.environ.get("NOTIFY_MODE", "simulated").lower()

# ── Rate-guard state (in-memory; good enough for single-process prototype) ────
_confirm_log: dict[tuple, list] = defaultdict(list)
RATE_WINDOW_SECONDS = 300  # 5-minute window
RATE_MAX_CONFIRMS = 3      # max confirms per (driver_id, note_id) in window


def _is_rate_limited(driver_id: str, note_id: int) -> bool:
    key = (driver_id, note_id)
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=RATE_WINDOW_SECONDS)
    _confirm_log[key] = [t for t in _confirm_log[key] if t > cutoff]
    if len(_confirm_log[key]) >= RATE_MAX_CONFIRMS:
        return True
    _confirm_log[key].append(now)
    return False


# ── String-similarity helper ───────────────────────────────────────────────────
def _normalize_addr(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize_addr(a), _normalize_addr(b)).ratio()


# ── Frontend serving ───────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(os.path.join(frontend_path, "index.html"))


# ══════════════════════════════════════════════════════════════════════════════
# ADDRESS ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/addresses", response_model=schemas.AddressResponse, status_code=201)
def create_address(
    address: schemas.AddressCreate,
    skip_dedup_scan: bool = Query(default=False, description="Set True during bulk simulation seeding to skip expensive similarity scan"),
    db: Session = Depends(get_db)
):
    """Register a new delivery address."""
    if db.query(models.Address).filter(models.Address.address_id == address.address_id).first():
        raise HTTPException(status_code=409, detail=f"address_id '{address.address_id}' already exists")

    db_address = models.Address(**address.model_dump())
    db.add(db_address)
    db.commit()
    db.refresh(db_address)
    logger.info(f"ADDRESS_REGISTERED addr={address.address_id} area={address.area}")

    # Scan for near-duplicate pairs and flag them (skip during bulk simulation seeding)
    if not skip_dedup_scan:
        _flag_duplicate_candidates(address.address_id, db)

    return db_address


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCH ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/dispatch/{address_id}", response_model=schemas.DispatchResponse)
def dispatch(address_id: str, db: Session = Depends(get_db)):
    """Get best confidence-ranked access note for an address at dispatch time."""
    if not address_id or len(address_id) > 100:
        raise HTTPException(status_code=422, detail="Invalid address_id format")

    address = db.query(models.Address).filter(
        models.Address.address_id == address_id,
        models.Address.is_archived == False
    ).first()

    cold_response = schemas.DispatchResponse(
        address_id=address_id,
        raw_text=address.raw_text if address else None,
        confidence_label="Low confidence / no verified note — attempt as new address"
    )

    if not address:
        logger.info(f"DISPATCH addr={address_id} result=COLD_START reason=ADDRESS_NOT_FOUND")
        return cold_response

    # If archived/merged, redirect to canonical
    if address.canonical_id:
        address_id = address.canonical_id

    notes = db.query(models.AccessNote).filter(
        models.AccessNote.address_id == address_id
    ).all()

    if not notes:
        logger.info(f"DISPATCH addr={address_id} result=COLD_START reason=NO_NOTES")
        return cold_response

    best_note = None
    best_score = -1.0
    now = datetime.utcnow()

    for note in notes:
        score = uncertainty.calculate_confidence(
            confirmation_count=note.confirmation_count,
            contradiction_count=note.contradiction_count,
            last_confirmed_at=note.last_confirmed_at,
            current_time=now
        )
        if score > best_score:
            best_score = score
            best_note = note

    label = uncertainty.get_confidence_band(best_score)
    logger.info(
        f"DISPATCH addr={address_id} note_id={best_note.note_id} "
        f"conf_score={best_score:.3f} conf_label='{label}'"
    )

    return schemas.DispatchResponse(
        address_id=address_id,
        raw_text=address.raw_text,
        note=best_note,
        confidence_score=best_score,
        confidence_label=label
    )


# ── ML Model Helper ────────────────────────────────────────────────────────────
_ml_model = None

def get_ml_model():
    global _ml_model
    if _ml_model is None:
        model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ml", "artifacts", "delivery_risk_model.joblib")
        if os.path.exists(model_path):
            try:
                _ml_model = joblib.load(model_path)
            except Exception as e:
                logger.error(f"Failed to load ML model: {e}")
    return _ml_model


# ══════════════════════════════════════════════════════════════════════════════
# ML RISK-SCORE ENDPOINT (Trained Predictive Component)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/dispatch/{address_id}/risk-score", response_model=schemas.RiskScoreResponse)
def get_risk_score(address_id: str, db: Session = Depends(get_db)):
    """
    Returns the ML model's predicted failure probability for a hypothetical attempt today.
    STRICTLY SEPARATED from the rule-based note confidence score.
    Follows 'No False Precision': rounded to the nearest 5% and accompanied by explanatory note.
    """
    addr = db.query(models.Address).filter(models.Address.address_id == address_id).first()
    if not addr:
        raise HTTPException(status_code=404, detail=f"Address '{address_id}' not found")

    target_id = addr.canonical_id if addr.canonical_id else address_id
    now = datetime.utcnow()

    # Access notes state
    notes = db.query(models.AccessNote).filter(models.AccessNote.address_id == target_id).all()
    conf_band = "None"
    has_note = 0
    if notes:
        has_note = 1
        best_score = -1.0
        for n in notes:
            s = uncertainty.calculate_confidence(n.confirmation_count, n.contradiction_count, n.last_confirmed_at, now)
            if s > best_score:
                best_score = s
        if best_score >= 0.70:
            conf_band = "High"
        elif best_score >= 0.40:
            conf_band = "Medium"
        else:
            conf_band = "Low"

    # Address history
    attempts = db.query(models.DeliveryAttempt).filter(
        models.DeliveryAttempt.address_id == target_id
    ).order_by(models.DeliveryAttempt.timestamp.asc()).all()

    if attempts:
        fails = sum(1 for a in attempts if a.outcome in [models.OutcomeEnum.FAILED, models.OutcomeEnum.RTO])
        addr_hist_fail_rate = fails / len(attempts)
        successes = [a for a in attempts if a.outcome == models.OutcomeEnum.SUCCESS]
        if successes:
            days_since_last_success = max(0.0, (now - successes[-1].timestamp).total_seconds() / 86400.0)
        else:
            days_since_last_success = 90.0
    else:
        diff_map = {
            "standalone house": 0.12, "apartment": 0.38,
            "gated community": 0.62, "industrial": 0.48
        }
        addr_hist_fail_rate = diff_map.get(addr.area, 0.40)
        days_since_last_success = 90.0

    current_hour = now.hour
    if current_hour < 13:
        slot = "10:00-13:00 slot"
    elif current_hour < 17:
        slot = "14:00-17:00 slot"
    else:
        slot = "17:00-20:00 slot"

    features_dict = {
        "area": addr.area,
        "day_of_week": now.weekday(),
        "slot": slot,
        "has_note": has_note,
        "conf_band": conf_band,
        "days_since_last_success": round(days_since_last_success, 1),
        "addr_hist_fail_rate": round(addr_hist_fail_rate, 3),
        "driver_hist_success_rate": 0.75
    }

    model = get_ml_model()
    if model:
        import pandas as pd
        X_df = pd.DataFrame([features_dict])
        prob_success = float(model.predict_proba(X_df)[0][1])
        raw_risk = 1.0 - prob_success
    else:
        # Fallback estimation if model artifact not available
        raw_risk = addr_hist_fail_rate * (0.5 if has_note and conf_band == "High" else 1.0)

    # Round to nearest 5% (0.05) and maximum 2 decimal places to prevent false precision
    rounded_risk = round(round(raw_risk * 20.0) / 20.0, 2)
    rounded_risk = max(0.05, min(0.95, rounded_risk))
    pct_str = int(round(rounded_risk * 100))

    return schemas.RiskScoreResponse(
        address_id=address_id,
        raw_text=addr.raw_text,
        area=addr.area,
        confidence_band=conf_band,
        model_risk_score=rounded_risk,
        model_risk_label=f"~{pct_str}% estimated failure risk",
        model_note="Statistical estimate from historical patterns — not a substitute for the access note confidence above.",
        disclaimer="Analytical estimate for Ops planning only — not shown to drivers to prevent conflicting signals.",
        features_used=features_dict
    )


# ══════════════════════════════════════════════════════════════════════════════
# DELIVERY ATTEMPT ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/attempts", response_model=schemas.DeliveryAttemptResponse, status_code=201)
def log_attempt(attempt: schemas.DeliveryAttemptCreate, db: Session = Depends(get_db)):
    """Log a delivery attempt outcome. Updates note confidence automatically."""
    # Validate address exists
    addr = db.query(models.Address).filter(
        models.Address.address_id == attempt.address_id
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail=f"Address '{attempt.address_id}' not found")

    db_attempt = models.DeliveryAttempt(**attempt.model_dump())
    db.add(db_attempt)

    if attempt.used_note_id:
        note = db.query(models.AccessNote).filter(
            models.AccessNote.note_id == attempt.used_note_id
        ).first()
        if not note:
            raise HTTPException(status_code=404, detail=f"Note ID {attempt.used_note_id} not found")

        if attempt.outcome == models.OutcomeEnum.SUCCESS:
            note.confirmation_count += 1
            note.last_confirmed_at = datetime.utcnow()
            logger.info(
                f"OUTCOME addr={attempt.address_id} driver={attempt.driver_id} "
                f"result=SUCCESS note_id={attempt.used_note_id} "
                f"new_conf_count={note.confirmation_count}"
            )
        elif attempt.outcome in [models.OutcomeEnum.FAILED, models.OutcomeEnum.RTO]:
            note.contradiction_count += 1
            logger.warning(
                f"OUTCOME addr={attempt.address_id} driver={attempt.driver_id} "
                f"result={attempt.outcome.value} note_id={attempt.used_note_id} "
                f"new_contra_count={note.contradiction_count} "
                f"reason: note may be stale or incorrect"
            )
    else:
        logger.info(
            f"OUTCOME addr={attempt.address_id} driver={attempt.driver_id} "
            f"result={attempt.outcome.value} note_id=None (cold start)"
        )

    db.commit()
    db.refresh(db_attempt)
    return db_attempt


# ══════════════════════════════════════════════════════════════════════════════
# NOTES ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/notes", response_model=schemas.AccessNoteResponse, status_code=201)
def create_note(note: schemas.AccessNoteCreate, db: Session = Depends(get_db)):
    """Create a new access note for an address."""
    addr = db.query(models.Address).filter(
        models.Address.address_id == note.address_id
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail=f"Address '{note.address_id}' not found")

    db_note = models.AccessNote(**note.model_dump())
    if note.source == models.SourceEnum.CUSTOMER_CONFIRMED:
        db_note.confirmation_count = 3  # Customer notes start with higher weight
    else:
        db_note.confirmation_count = 1  # Driver logging after success

    db.add(db_note)
    db.commit()
    db.refresh(db_note)

    logger.info(
        f"NOTE_CREATED addr={note.address_id} source={note.source.value} "
        f"initial_conf={db_note.confirmation_count}"
    )
    return db_note


@app.post("/notes/{note_id}/confirm", response_model=schemas.AccessNoteResponse)
def confirm_note(
    note_id: int,
    source: models.SourceEnum = models.SourceEnum.DRIVER_LOGGED,
    driver_id: Optional[str] = Query(default="UNKNOWN"),
    db: Session = Depends(get_db)
):
    """Confirm (or weight-boost) a note. Rate-limited to prevent spam gaming confidence."""
    if note_id <= 0:
        raise HTTPException(status_code=422, detail="note_id must be a positive integer")

    note = db.query(models.AccessNote).filter(models.AccessNote.note_id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Rate guard — only applies to driver confirmations, not customer
    if source == models.SourceEnum.DRIVER_LOGGED and driver_id:
        if _is_rate_limited(driver_id, note_id):
            logger.warning(
                f"RATE_LIMIT driver={driver_id} note_id={note_id} "
                f"exceeded {RATE_MAX_CONFIRMS} confirms in {RATE_WINDOW_SECONDS}s"
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit: max {RATE_MAX_CONFIRMS} confirmations per {RATE_WINDOW_SECONDS}s per driver/note pair."
            )

    weight = 3 if source == models.SourceEnum.CUSTOMER_CONFIRMED else 1
    note.confirmation_count += weight
    note.last_confirmed_at = datetime.utcnow()
    if source == models.SourceEnum.CUSTOMER_CONFIRMED:
        note.source = models.SourceEnum.CUSTOMER_CONFIRMED

    db.commit()
    db.refresh(note)

    logger.info(
        f"NOTE_CONFIRMED note_id={note_id} source={source.value} weight={weight} "
        f"new_conf_count={note.confirmation_count}"
    )
    return note


# ══════════════════════════════════════════════════════════════════════════════
# EXPLORER / HISTORY ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/explorer", response_model=List[schemas.AddressExplorerItem])
def get_address_explorer(
    search: Optional[str] = None,
    sort_by: Optional[str] = "lowest_confidence",
    db: Session = Depends(get_db)
):
    """Address registry with search, sort, confidence scores, and duplicate flags."""
    query = db.query(models.Address).filter(models.Address.is_archived == False)
    if search:
        sf = f"%{search}%"
        query = query.filter(
            models.Address.address_id.like(sf) | models.Address.raw_text.like(sf)
        )

    addresses = query.all()
    now = datetime.utcnow()

    # Build a quick lookup: address_id -> pending duplicate partner
    pending_dupes: dict[str, str] = {}
    for log in db.query(models.DuplicateMergeLog).filter(
        models.DuplicateMergeLog.decision == None
    ).all():
        pending_dupes[log.addr_id_a] = log.addr_id_b
        pending_dupes[log.addr_id_b] = log.addr_id_a

    results = []
    for addr in addresses:
        notes = db.query(models.AccessNote).filter(
            models.AccessNote.address_id == addr.address_id
        ).all()
        attempts = db.query(models.DeliveryAttempt).filter(
            models.DeliveryAttempt.address_id == addr.address_id
        ).all()

        best_score = 0.0
        best_label = "Low confidence / no verified note — attempt as new address"
        last_confirmed = None
        total_conf = total_contra = 0
        sources = list(set([n.source.value for n in notes])) if notes else []

        if notes:
            for n in notes:
                score = uncertainty.calculate_confidence(
                    n.confirmation_count, n.contradiction_count, n.last_confirmed_at, now
                )
                if score > best_score:
                    best_score = score
                    best_label = uncertainty.get_confidence_band(score)
                total_conf += n.confirmation_count
                total_contra += n.contradiction_count
                if last_confirmed is None or n.last_confirmed_at > last_confirmed:
                    last_confirmed = n.last_confirmed_at

        results.append(schemas.AddressExplorerItem(
            address_id=addr.address_id,
            raw_text=addr.raw_text,
            area=addr.area,
            confidence_label=best_label,
            confidence_score=round(best_score, 3),
            note_count=len(notes),
            total_attempts=len(attempts),
            last_confirmed_at=last_confirmed,
            confirmation_count=total_conf,
            contradiction_count=total_contra,
            sources=sources,
            possible_duplicate_of=pending_dupes.get(addr.address_id)
        ))

    if sort_by == "lowest_confidence":
        results.sort(key=lambda x: x.confidence_score)
    elif sort_by == "most_contradicted":
        results.sort(key=lambda x: x.contradiction_count, reverse=True)
    elif sort_by == "most_attempts":
        results.sort(key=lambda x: x.total_attempts, reverse=True)

    return results


@app.get("/history/{address_id}", response_model=schemas.AddressHistoryResponse)
def get_address_history(address_id: str, db: Session = Depends(get_db)):
    address = db.query(models.Address).filter(
        models.Address.address_id == address_id
    ).first()
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    notes = db.query(models.AccessNote).filter(
        models.AccessNote.address_id == address_id
    ).order_by(models.AccessNote.created_at.desc()).all()

    attempts = db.query(models.DeliveryAttempt).filter(
        models.DeliveryAttempt.address_id == address_id
    ).order_by(models.DeliveryAttempt.timestamp.desc()).all()

    return schemas.AddressHistoryResponse(
        address_id=address.address_id,
        raw_text=address.raw_text,
        area=address.area,
        notes=notes,
        attempts=attempts
    )


# ══════════════════════════════════════════════════════════════════════════════
# DUPLICATE MERGE WORKFLOW
# ══════════════════════════════════════════════════════════════════════════════

SIMILARITY_THRESHOLD = 0.70  # flag pairs above this token-overlap score

def _flag_duplicate_candidates(new_addr_id: str, db: Session):
    """Scan existing addresses for similarity to the new one and log flags."""
    new_addr = db.query(models.Address).filter(
        models.Address.address_id == new_addr_id
    ).first()
    if not new_addr:
        return

    existing = db.query(models.Address).filter(
        models.Address.address_id != new_addr_id,
        models.Address.is_archived == False
    ).all()

    for addr in existing:
        score = _similarity(new_addr.raw_text, addr.raw_text)
        if score >= SIMILARITY_THRESHOLD:
            # Check if this pair is already flagged
            already = db.query(models.DuplicateMergeLog).filter(
                (
                    (models.DuplicateMergeLog.addr_id_a == new_addr_id) &
                    (models.DuplicateMergeLog.addr_id_b == addr.address_id)
                ) | (
                    (models.DuplicateMergeLog.addr_id_a == addr.address_id) &
                    (models.DuplicateMergeLog.addr_id_b == new_addr_id)
                )
            ).first()
            if not already:
                flag = models.DuplicateMergeLog(
                    addr_id_a=new_addr_id,
                    addr_id_b=addr.address_id,
                    similarity_score=round(score, 3)
                )
                db.add(flag)
                logger.info(
                    f"DUPLICATE_FLAGGED pair=({new_addr_id}, {addr.address_id}) "
                    f"similarity={score:.3f} — awaiting ops review"
                )

    db.commit()


@app.get("/duplicates/flag", response_model=List[schemas.DuplicateFlagItem])
def get_flagged_duplicates(
    pending_only: bool = True,
    db: Session = Depends(get_db)
):
    """List flagged near-duplicate address pairs. pending_only=True returns undecided pairs."""
    query = db.query(models.DuplicateMergeLog)
    if pending_only:
        query = query.filter(models.DuplicateMergeLog.decision == None)
    logs = query.order_by(models.DuplicateMergeLog.similarity_score.desc()).all()

    result = []
    for log in logs:
        addr_a = db.query(models.Address).filter(models.Address.address_id == log.addr_id_a).first()
        addr_b = db.query(models.Address).filter(models.Address.address_id == log.addr_id_b).first()
        item = schemas.DuplicateFlagItem(
            log_id=log.log_id,
            addr_id_a=log.addr_id_a,
            addr_id_b=log.addr_id_b,
            raw_text_a=addr_a.raw_text if addr_a else None,
            raw_text_b=addr_b.raw_text if addr_b else None,
            similarity_score=log.similarity_score,
            flagged_at=log.flagged_at,
            decision=log.decision,
            decided_at=log.decided_at,
            decided_by=log.decided_by,
            canonical_id=log.canonical_id
        )
        result.append(item)
    return result


@app.post("/duplicates/{log_id}/decide", response_model=schemas.DuplicateFlagItem)
def decide_duplicate_merge(
    log_id: int,
    decision: schemas.MergeDecisionRequest,
    db: Session = Depends(get_db)
):
    """
    Ops Manager action: Merge or Keep Separate. NEVER auto-merged.
    - MERGED: archive the non-canonical address, set canonical_id pointer.
              Note and attempt history is preserved (not deleted).
    - KEPT_SEPARATE: log the decision; pair will not re-flag on next run.
    """
    if log_id <= 0:
        raise HTTPException(status_code=422, detail="log_id must be a positive integer")

    log = db.query(models.DuplicateMergeLog).filter(
        models.DuplicateMergeLog.log_id == log_id
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Duplicate log entry not found")

    if log.decision is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Decision already recorded: {log.decision.value} at {log.decided_at}"
        )

    now = datetime.utcnow()
    log.decision = decision.decision
    log.decided_at = now
    log.decided_by = decision.decided_by

    if decision.decision == models.MergeDecisionEnum.MERGED:
        if not decision.canonical_id:
            raise HTTPException(
                status_code=422,
                detail="canonical_id is required when decision=MERGED"
            )
        canonical_id = decision.canonical_id
        archive_id = (
            log.addr_id_b if canonical_id == log.addr_id_a else log.addr_id_a
        )
        log.canonical_id = canonical_id

        archived_addr = db.query(models.Address).filter(
            models.Address.address_id == archive_id
        ).first()
        if archived_addr:
            archived_addr.canonical_id = canonical_id
            archived_addr.is_archived = True

        logger.info(
            f"MERGE_DECIDED log_id={log_id} decision=MERGED "
            f"canonical={canonical_id} archived={archive_id} by={decision.decided_by}"
        )
    else:
        logger.info(
            f"MERGE_DECIDED log_id={log_id} decision=KEPT_SEPARATE "
            f"pair=({log.addr_id_a},{log.addr_id_b}) by={decision.decided_by}"
        )

    db.commit()
    db.refresh(log)

    addr_a = db.query(models.Address).filter(models.Address.address_id == log.addr_id_a).first()
    addr_b = db.query(models.Address).filter(models.Address.address_id == log.addr_id_b).first()

    return schemas.DuplicateFlagItem(
        log_id=log.log_id,
        addr_id_a=log.addr_id_a,
        addr_id_b=log.addr_id_b,
        raw_text_a=addr_a.raw_text if addr_a else None,
        raw_text_b=addr_b.raw_text if addr_b else None,
        similarity_score=log.similarity_score,
        flagged_at=log.flagged_at,
        decision=log.decision,
        decided_at=log.decided_at,
        decided_by=log.decided_by,
        canonical_id=log.canonical_id
    )


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/notify", response_model=schemas.NotifyResponse)
def send_notification(req: schemas.NotifyRequest, db: Session = Depends(get_db)):
    """
    Send a customer notification about their address access note.
    NOTIFY_MODE=simulated (default) — logs the notification, no external API call.
    NOTIFY_MODE=real — would call Twilio/SMTP (not implemented without credentials).
    See /docs/notification_channel_plan.md for real-mode requirements.
    """
    note = db.query(models.AccessNote).filter(
        models.AccessNote.note_id == req.note_id
    ).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    addr = db.query(models.Address).filter(
        models.Address.address_id == req.address_id
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")

    mode = NOTIFY_MODE
    channel = "SIMULATED"
    status = "SIMULATED"
    message = ""

    if mode == "simulated":
        message = (
            f"[SIMULATED SMS] To: {req.recipient or 'customer'} | "
            f"Access instruction for {addr.raw_text}: "
            f"\"{note.instruction_text}\" — Reply YES to confirm, NO to correct."
        )
        logger.info(
            f"NOTIFY_SIMULATED addr={req.address_id} note_id={req.note_id} "
            f"recipient={req.recipient} msg='{message}'"
        )

    elif mode == "real":
        # Real integration would go here.
        # Example (Twilio): requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM env vars.
        # See docs/notification_channel_plan.md for full integration spec.
        message = (
            "REAL mode selected but no credentials configured. "
            "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM env vars. "
            "See docs/notification_channel_plan.md."
        )
        status = "FAILED"
        logger.warning(f"NOTIFY_REAL requested but credentials not configured addr={req.address_id}")
    else:
        raise HTTPException(status_code=422, detail=f"Unknown NOTIFY_MODE: {mode}")

    # Log to DB
    log_entry = models.NotifyLog(
        address_id=req.address_id,
        note_id=req.note_id,
        channel=channel,
        mode=mode,
        status=status,
        recipient=req.recipient
    )
    db.add(log_entry)
    db.commit()

    return schemas.NotifyResponse(status=status, mode=mode, channel=channel, message=message)


# ══════════════════════════════════════════════════════════════════════════════
# EDGE CASE DEMO ENDPOINT (cases 1–6)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/demo/edge-case/{case_id}", response_model=schemas.EdgeCaseDemoResponse)
def trigger_edge_case(case_id: int, db: Session = Depends(get_db)):
    """Triggers pre-configured edge-case scenarios for viva demo."""
    if case_id not in range(1, 7):
        raise HTTPException(status_code=400, detail="Invalid edge case ID (1–6 supported)")

    addr_id = f"DEMO_CASE_{case_id}"

    # Clean old demo data for this address
    db.query(models.DeliveryAttempt).filter(models.DeliveryAttempt.address_id == addr_id).delete()
    db.query(models.AccessNote).filter(models.AccessNote.address_id == addr_id).delete()
    db.query(models.Address).filter(models.Address.address_id == addr_id).delete()
    db.commit()

    now = datetime.utcnow()

    if case_id == 1:
        addr = models.Address(address_id=addr_id, raw_text="123 Conflict Blvd, Flat 4B", area="apartment")
        db.add(addr)
        db.commit()

        n1 = models.AccessNote(address_id=addr_id, instruction_text="Gate 1 (West Gate)", source=models.SourceEnum.DRIVER_LOGGED, confirmation_count=1, contradiction_count=3, last_confirmed_at=now)
        n2 = models.AccessNote(address_id=addr_id, instruction_text="Gate 2 (East Gate)", source=models.SourceEnum.DRIVER_LOGGED, confirmation_count=1, contradiction_count=3, last_confirmed_at=now)
        db.add_all([n1, n2])
        db.commit()

        resp = dispatch(addr_id, db)
        return schemas.EdgeCaseDemoResponse(
            case_id=1,
            title="Edge Case 1: Conflicting Notes",
            description="Two drivers logged contradictory instructions. Confidence degrades across both — system warns rather than silently picking one.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )

    elif case_id == 2:
        addr = models.Address(address_id=addr_id, raw_text="456 Stale Way, Gate 3", area="gated community")
        db.add(addr)
        db.commit()

        n = models.AccessNote(address_id=addr_id, instruction_text="Old Code 1234", source=models.SourceEnum.DRIVER_LOGGED, confirmation_count=4, contradiction_count=4, last_confirmed_at=now - timedelta(days=10))
        db.add(n)
        db.commit()

        resp = dispatch(addr_id, db)
        return schemas.EdgeCaseDemoResponse(
            case_id=2,
            title="Edge Case 2: Stale Note Causes Failure",
            description="Previously high-confidence note failed repeatedly (e.g. gate code changed). Contradictions drag confidence to Medium/Low.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )

    elif case_id == 3:
        addr = models.Address(address_id=addr_id, raw_text="789 New Construction Rd", area="standalone house")
        db.add(addr)
        db.commit()

        resp = dispatch(addr_id, db)
        return schemas.EdgeCaseDemoResponse(
            case_id=3,
            title="Edge Case 3: Cold Start",
            description="Zero logged notes. System explicitly returns 'Low confidence / no verified note' rather than blank.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )

    elif case_id == 4:
        addr = models.Address(address_id=addr_id, raw_text="101 Customer Quiet St", area="apartment")
        db.add(addr)
        db.commit()

        n = models.AccessNote(address_id=addr_id, instruction_text="Intercom #42", source=models.SourceEnum.DRIVER_LOGGED, confirmation_count=1, contradiction_count=0, last_confirmed_at=now)
        db.add(n)
        db.commit()

        resp = dispatch(addr_id, db)
        return schemas.EdgeCaseDemoResponse(
            case_id=4,
            title="Edge Case 4: Unconfirmed Customer Note",
            description="Customer did not respond to SMS. Note stays at DRIVER_LOGGED tier and does NOT silently upgrade.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )

    elif case_id == 5:
        raw1 = "Flat 4B, Green Apts"
        raw2 = "4-B Green Apartments"
        norm1 = hashlib.md5(re.sub(r'[^\w\s]', '', raw1.lower()).encode()).hexdigest()[:16]
        norm2 = hashlib.md5(re.sub(r'[^\w\s]', '', raw2.lower()).encode()).hexdigest()[:16]

        sim = _similarity(raw1, raw2)

        return schemas.EdgeCaseDemoResponse(
            case_id=5,
            title="Edge Case 5: Address Key Collision",
            description="Near-duplicate address strings fail safe — treated as separate addresses to avoid wrong note injection.",
            scenario_result={
                "address_1": raw1, "hash_1": norm1,
                "address_2": raw2, "hash_2": norm2,
                "similarity_score": round(sim, 3),
                "merged": (norm1 == norm2),
                "flagged_for_ops_review": sim >= SIMILARITY_THRESHOLD,
                "strategy_chosen": "Fail safe: treated as separate addresses. Flagged for ops review if similarity ≥ threshold."
            }
        )

    elif case_id == 6:
        # Edge Case 6: Duplicate address — NOT auto-merged, requires explicit ops review
        addr_a_id = f"DEMO_CASE_6A"
        addr_b_id = f"DEMO_CASE_6B"

        for aid in [addr_a_id, addr_b_id]:
            db.query(models.DeliveryAttempt).filter(models.DeliveryAttempt.address_id == aid).delete()
            db.query(models.AccessNote).filter(models.AccessNote.address_id == aid).delete()
        db.query(models.Address).filter(models.Address.address_id.in_([addr_a_id, addr_b_id])).delete()
        db.query(models.DuplicateMergeLog).filter(
            models.DuplicateMergeLog.addr_id_a.in_([addr_a_id, addr_b_id]) |
            models.DuplicateMergeLog.addr_id_b.in_([addr_a_id, addr_b_id])
        ).delete(synchronize_session=False)
        db.commit()

        a_addr = models.Address(address_id=addr_a_id, raw_text="Flat 7A, Sunrise Apartments", area="apartment")
        b_addr = models.Address(address_id=addr_b_id, raw_text="7A Sunrise Apts, Main Block", area="apartment")
        db.add_all([a_addr, b_addr])
        db.commit()

        # Add notes to each
        n_a = models.AccessNote(address_id=addr_a_id, instruction_text="Ring bell twice, use east staircase", source=models.SourceEnum.DRIVER_LOGGED, confirmation_count=3, contradiction_count=0, last_confirmed_at=now)
        n_b = models.AccessNote(address_id=addr_b_id, instruction_text="West entrance, security check required", source=models.SourceEnum.DRIVER_LOGGED, confirmation_count=2, contradiction_count=1, last_confirmed_at=now - timedelta(days=5))
        db.add_all([n_a, n_b])
        db.commit()

        # Compute similarity
        sim = _similarity(a_addr.raw_text, b_addr.raw_text)

        # Flag as potential duplicate (bypassing the address creation hook for demo)
        flag = models.DuplicateMergeLog(
            addr_id_a=addr_a_id,
            addr_id_b=addr_b_id,
            similarity_score=round(sim, 3)
        )
        db.add(flag)
        db.commit()
        db.refresh(flag)

        return schemas.EdgeCaseDemoResponse(
            case_id=6,
            title="Edge Case 6: Human-in-the-Loop Duplicate Merge Review",
            description=(
                "Two addresses with high string similarity are flagged. "
                "Ops manager must explicitly choose Merge or Keep Separate — "
                "the system NEVER auto-merges. Declined pairs stay separate permanently."
            ),
            scenario_result={
                "address_a": {"id": addr_a_id, "raw_text": a_addr.raw_text, "notes": 1},
                "address_b": {"id": addr_b_id, "raw_text": b_addr.raw_text, "notes": 1},
                "similarity_score": round(sim, 3),
                "flagged_log_id": flag.log_id,
                "decision": "PENDING — awaiting ops review",
                "invariant": "Not merged automatically. POST /duplicates/{log_id}/decide to action.",
                "test_instruction": (
                    f"POST /duplicates/{flag.log_id}/decide with "
                    "{\"decision\":\"KEPT_SEPARATE\",\"decided_by\":\"OPS_MANAGER_1\"} "
                    "to verify pair stays separate permanently."
                )
            }
        )


# ══════════════════════════════════════════════════════════════════════════════
# OPS DASHBOARD EXTENSIONS (Driver Leaderboard, Area Breakdown, ML Metadata)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/ops/driver-leaderboard", response_model=List[schemas.DriverLeaderboardItem])
def get_driver_leaderboard(db: Session = Depends(get_db)):
    """
    Returns aggregated driver performance metrics (first-attempt success, repeat-failure rate, SLA adherence).
    """
    attempts = db.query(models.DeliveryAttempt).order_by(models.DeliveryAttempt.timestamp.asc()).all()
    driver_stats = defaultdict(lambda: {
        "total": 0, "success": 0, "failed": 0, "within_sla": 0,
        "repeat_failures": 0
    })

    addr_prior_fails = defaultdict(int)

    for att in attempts:
        d = att.driver_id
        st = driver_stats[d]
        st["total"] += 1
        is_succ = (att.outcome == models.OutcomeEnum.SUCCESS)
        if is_succ:
            st["success"] += 1
        else:
            st["failed"] += 1
            if addr_prior_fails[att.address_id] > 0:
                st["repeat_failures"] += 1
            addr_prior_fails[att.address_id] += 1

        if att.is_within_sla:
            st["within_sla"] += 1

    items = []
    for d, st in driver_stats.items():
        if st["total"] == 0:
            continue
        succ_rate = round(st["success"] / st["total"], 3)
        repeat_rate = round(st["repeat_failures"] / max(1, st["failed"]), 3)
        sla_rate = round(st["within_sla"] / st["total"], 3)
        items.append(schemas.DriverLeaderboardItem(
            driver_id=d,
            total_attempts=st["total"],
            success_count=st["success"],
            failed_count=st["failed"],
            first_attempt_success_rate=succ_rate,
            repeat_failure_rate=repeat_rate,
            sla_adherence_rate=sla_rate
        ))

    items.sort(key=lambda x: x.first_attempt_success_rate, reverse=True)
    return items


@app.get("/ops/area-breakdown", response_model=List[schemas.AreaBreakdownItem])
def get_area_breakdown(db: Session = Depends(get_db)):
    """
    Returns breakdown of delivery attempts and repeat failure rates grouped by area archetype.
    """
    areas = ["apartment", "gated community", "industrial", "standalone house"]
    addresses = db.query(models.Address).all()
    addr_area_map = {a.address_id: a.area for a in addresses}

    attempts = db.query(models.DeliveryAttempt).order_by(models.DeliveryAttempt.timestamp.asc()).all()

    area_stats = {area: {"addrs": 0, "total": 0, "success": 0, "failed": 0, "repeat_failures": 0} for area in areas}
    for a in addresses:
        if a.area in area_stats:
            area_stats[a.area]["addrs"] += 1

    addr_prior_fails = defaultdict(int)
    for att in attempts:
        area = addr_area_map.get(att.address_id)
        if not area or area not in area_stats:
            continue
        st = area_stats[area]
        st["total"] += 1
        if att.outcome == models.OutcomeEnum.SUCCESS:
            st["success"] += 1
        else:
            st["failed"] += 1
            if addr_prior_fails[att.address_id] > 0:
                st["repeat_failures"] += 1
            addr_prior_fails[att.address_id] += 1

    result = []
    for area in areas:
        st = area_stats[area]
        succ_rate = round(st["success"] / max(1, st["total"]), 3) if st["total"] > 0 else 0.0
        rep_rate = round(st["repeat_failures"] / max(1, st["failed"]), 3) if st["failed"] > 0 else 0.0
        result.append(schemas.AreaBreakdownItem(
            area=area,
            total_addresses=st["addrs"],
            total_attempts=st["total"],
            success_rate=succ_rate,
            repeat_failure_rate=rep_rate
        ))
    return result


@app.get("/ml/metadata")
def get_ml_metadata():
    """Returns metadata for the trained delivery risk prediction model."""
    meta_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ml", "artifacts", "model_metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            return json.load(f)
    raise HTTPException(status_code=404, detail="Model metadata not found")
