from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import os
import re
import hashlib

from . import models, schemas, uncertainty
from .database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Access-Instruction Capture & Reuse System")

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

@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(os.path.join(frontend_path, "index.html"))

@app.post("/addresses", response_model=schemas.AddressResponse)
def create_address(address: schemas.AddressCreate, db: Session = Depends(get_db)):
    db_address = models.Address(**address.model_dump())
    db.add(db_address)
    db.commit()
    db.refresh(db_address)
    return db_address

@app.get("/dispatch/{address_id}", response_model=schemas.DispatchResponse)
def dispatch(address_id: str, db: Session = Depends(get_db)):
    address = db.query(models.Address).filter(models.Address.address_id == address_id).first()
    if not address:
        return schemas.DispatchResponse(
            address_id=address_id,
            confidence_label="Low confidence / no verified note — attempt as new address"
        )
    
    notes = db.query(models.AccessNote).filter(models.AccessNote.address_id == address_id).all()
    if not notes:
        return schemas.DispatchResponse(
            address_id=address_id,
            confidence_label="Low confidence / no verified note — attempt as new address"
        )
    
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
            
    return schemas.DispatchResponse(
        address_id=address_id,
        note=best_note,
        confidence_score=best_score,
        confidence_label=uncertainty.get_confidence_band(best_score)
    )

@app.post("/attempts", response_model=schemas.DeliveryAttemptResponse)
def log_attempt(attempt: schemas.DeliveryAttemptCreate, db: Session = Depends(get_db)):
    db_attempt = models.DeliveryAttempt(**attempt.model_dump())
    db.add(db_attempt)
    
    if attempt.used_note_id:
        note = db.query(models.AccessNote).filter(models.AccessNote.note_id == attempt.used_note_id).first()
        if note:
            if attempt.outcome == models.OutcomeEnum.SUCCESS:
                note.confirmation_count += 1
                note.last_confirmed_at = datetime.utcnow()
            elif attempt.outcome in [models.OutcomeEnum.FAILED, models.OutcomeEnum.RTO]:
                note.contradiction_count += 1
    
    db.commit()
    db.refresh(db_attempt)
    return db_attempt

@app.post("/notes", response_model=schemas.AccessNoteResponse)
def create_note(note: schemas.AccessNoteCreate, db: Session = Depends(get_db)):
    db_note = models.AccessNote(**note.model_dump())
    if note.source == models.SourceEnum.CUSTOMER_CONFIRMED:
        db_note.confirmation_count = 3 # Customer notes start with higher initial weight
    else:
        db_note.confirmation_count = 1 # Driver logging after success
        
    db.add(db_note)
    db.commit()
    db.refresh(db_note)
    return db_note

@app.post("/notes/{note_id}/confirm", response_model=schemas.AccessNoteResponse)
def confirm_note(note_id: int, source: models.SourceEnum = models.SourceEnum.DRIVER_LOGGED, db: Session = Depends(get_db)):
    note = db.query(models.AccessNote).filter(models.AccessNote.note_id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
        
    weight = 3 if source == models.SourceEnum.CUSTOMER_CONFIRMED else 1
    note.confirmation_count += weight
    note.last_confirmed_at = datetime.utcnow()
    if source == models.SourceEnum.CUSTOMER_CONFIRMED:
        note.source = models.SourceEnum.CUSTOMER_CONFIRMED
        
    db.commit()
    db.refresh(note)
    return note

# --- NEW PHASE 2 ENDPOINTS ---

@app.get("/explorer", response_model=List[schemas.AddressExplorerItem])
def get_address_explorer(
    search: Optional[str] = None,
    sort_by: Optional[str] = "lowest_confidence",
    db: Session = Depends(get_db)
):
    query = db.query(models.Address)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(models.Address.address_id.like(search_filter) | models.Address.raw_text.like(search_filter))
        
    addresses = query.all()
    results = []
    now = datetime.utcnow()
    
    for addr in addresses:
        notes = db.query(models.AccessNote).filter(models.AccessNote.address_id == addr.address_id).all()
        attempts = db.query(models.DeliveryAttempt).filter(models.DeliveryAttempt.address_id == addr.address_id).all()
        
        best_score = 0.0
        best_label = "Low confidence / no verified note — attempt as new address"
        last_confirmed = None
        total_conf = 0
        total_contra = 0
        sources = list(set([n.source.value for n in notes])) if notes else []
        
        if notes:
            for n in notes:
                score = uncertainty.calculate_confidence(n.confirmation_count, n.contradiction_count, n.last_confirmed_at, now)
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
            sources=sources
        ))
        
    # Sorting logic
    if sort_by == "lowest_confidence":
        results.sort(key=lambda x: x.confidence_score)
    elif sort_by == "most_contradicted":
        results.sort(key=lambda x: x.contradiction_count, reverse=True)
    elif sort_by == "most_attempts":
        results.sort(key=lambda x: x.total_attempts, reverse=True)
        
    return results

@app.get("/history/{address_id}", response_model=schemas.AddressHistoryResponse)
def get_address_history(address_id: str, db: Session = Depends(get_db)):
    address = db.query(models.Address).filter(models.Address.address_id == address_id).first()
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
        
    notes = db.query(models.AccessNote).filter(models.AccessNote.address_id == address_id).order_by(models.AccessNote.created_at.desc()).all()
    attempts = db.query(models.DeliveryAttempt).filter(models.DeliveryAttempt.address_id == address_id).order_by(models.DeliveryAttempt.timestamp.desc()).all()
    
    return schemas.AddressHistoryResponse(
        address_id=address.address_id,
        raw_text=address.raw_text,
        area=address.area,
        notes=notes,
        attempts=attempts
    )

@app.post("/demo/edge-case/{case_id}", response_model=schemas.EdgeCaseDemoResponse)
def trigger_edge_case(case_id: int, db: Session = Depends(get_db)):
    """Triggers pre-configured pytest scenarios live for the viva demo."""
    addr_id = f"DEMO_CASE_{case_id}"
    
    # Clean old demo data for this address
    db.query(models.DeliveryAttempt).filter(models.DeliveryAttempt.address_id == addr_id).delete()
    db.query(models.AccessNote).filter(models.AccessNote.address_id == addr_id).delete()
    db.query(models.Address).filter(models.Address.address_id == addr_id).delete()
    db.commit()
    
    now = datetime.utcnow()
    
    if case_id == 1:
        # Conflicting Notes
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
            description="Two drivers logged contradictory instructions in a short window. Confidence degrades across both notes rather than silently picking one.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )
        
    elif case_id == 2:
        # Stale Note Causes Failure
        addr = models.Address(address_id=addr_id, raw_text="456 Stale Way, Gate 3", area="gated community")
        db.add(addr)
        db.commit()
        
        # Was high confidence (4 confirmations), now failed 4 times
        n = models.AccessNote(address_id=addr_id, instruction_text="Old Code 1234", source=models.SourceEnum.DRIVER_LOGGED, confirmation_count=4, contradiction_count=4, last_confirmed_at=now - timedelta(days=10))
        db.add(n)
        db.commit()
        
        resp = dispatch(addr_id, db)
        return schemas.EdgeCaseDemoResponse(
            case_id=2,
            title="Edge Case 2: Stale Note Causes Failure",
            description="A previously high-confidence note failed repeatedly (e.g. gate code changed). Contradictions drag confidence down to Medium/Low.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )
        
    elif case_id == 3:
        # Cold Start
        addr = models.Address(address_id=addr_id, raw_text="789 New Construction Rd", area="standalone house")
        db.add(addr)
        db.commit()
        
        resp = dispatch(addr_id, db)
        return schemas.EdgeCaseDemoResponse(
            case_id=3,
            title="Edge Case 3: Cold Start",
            description="Address has zero logged notes. System explicitly returns 'Low confidence / no verified note' rather than a blank field.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )
        
    elif case_id == 4:
        # Customer Declines / Unconfirmed
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
            description="Customer did not respond to SMS. The note stays at DRIVER_LOGGED tier and does NOT silently upgrade to CUSTOMER_CONFIRMED.",
            scenario_result={"address_id": addr_id, "dispatch_response": resp.model_dump()}
        )
        
    elif case_id == 5:
        # Address Key Collision / Near Duplicate
        raw1 = "Flat 4B, Green Apts"
        raw2 = "4-B Green Apartments"
        norm1 = hashlib.md5(re.sub(r'[^\w\s]', '', raw1.lower()).encode()).hexdigest()[:16]
        norm2 = hashlib.md5(re.sub(r'[^\w\s]', '', raw2.lower()).encode()).hexdigest()[:16]
        
        return schemas.EdgeCaseDemoResponse(
            case_id=5,
            title="Edge Case 5: Address Key Collision",
            description="Near-duplicate address strings that fail exact normalization treat addresses separately to fail safe rather than merging unrelated locations.",
            scenario_result={
                "address_1": raw1, "hash_1": norm1,
                "address_2": raw2, "hash_2": norm2,
                "merged": (norm1 == norm2),
                "strategy_chosen": "Fail safe: treated as separate addresses to avoid wrong note injection."
            }
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid edge case ID")
