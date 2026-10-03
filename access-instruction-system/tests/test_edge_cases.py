"""
test_edge_cases.py — Edge Case Test Suite (6 cases)
=====================================================
All 6 edge cases for the Access-Instruction System.
Run with: python -m pytest tests/test_edge_cases.py -v
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import re
import hashlib

from backend.main import app, SIMILARITY_THRESHOLD
from backend.database import Base, engine, get_db
from backend.models import SourceEnum, OutcomeEnum

# Simple normalizer for testing Address Key Collision
def normalize_address(raw: str) -> str:
    normalized = re.sub(r'[^\w\s]', '', raw.lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.md5(normalized.encode()).hexdigest()[:16]

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# ── Edge Case 3: Cold Start ────────────────────────────────────────────────────
def test_cold_start():
    """Cold start: address with zero notes explicitly returns low confidence."""
    client.post("/addresses", json={"address_id": "ADDR_COLD", "raw_text": "123 Cold St", "area": "apartment"})
    resp = client.get("/dispatch/ADDR_COLD")
    assert resp.status_code == 200
    data = resp.json()
    assert data["note"] is None
    assert "Low confidence / no verified note" in data["confidence_label"]


# ── Edge Case 1: Conflicting Notes ────────────────────────────────────────────
def test_conflicting_notes():
    """Conflicting notes: contradictions lower confidence across both notes."""
    client.post("/addresses", json={"address_id": "ADDR_CONF", "raw_text": "123 Conflict", "area": "apartment"})

    n1 = client.post("/notes", json={"address_id": "ADDR_CONF", "instruction_text": "Gate 1 entry", "source": "DRIVER_LOGGED"}).json()
    n2 = client.post("/notes", json={"address_id": "ADDR_CONF", "instruction_text": "Gate 2 entry", "source": "DRIVER_LOGGED"}).json()

    for _ in range(3):
        client.post("/attempts", json={"address_id": "ADDR_CONF", "outcome": "FAILED", "used_note_id": n1["note_id"], "driver_id": "D1"})
        client.post("/attempts", json={"address_id": "ADDR_CONF", "outcome": "FAILED", "used_note_id": n2["note_id"], "driver_id": "D2"})

    resp = client.get("/dispatch/ADDR_CONF").json()
    assert resp["confidence_score"] < 0.4, f"Expected low confidence, got {resp['confidence_score']}"


# ── Edge Case 2: Stale Note Causes Failure ────────────────────────────────────
def test_stale_note_causes_failure():
    """Stale note: previously high-confidence drops after failures."""
    client.post("/addresses", json={"address_id": "ADDR_STALE", "raw_text": "123 Stale Ave", "area": "apartment"})
    n = client.post("/notes", json={"address_id": "ADDR_STALE", "instruction_text": "Old gate code", "source": "DRIVER_LOGGED"}).json()

    for _ in range(3):
        client.post("/attempts", json={"address_id": "ADDR_STALE", "outcome": "SUCCESS", "used_note_id": n["note_id"], "driver_id": "D1"})

    resp1 = client.get("/dispatch/ADDR_STALE").json()
    assert resp1["confidence_score"] >= 0.7
    assert "High confidence" in resp1["confidence_label"]

    for _ in range(4):
        client.post("/attempts", json={"address_id": "ADDR_STALE", "outcome": "FAILED", "used_note_id": n["note_id"], "driver_id": "D2"})

    resp2 = client.get("/dispatch/ADDR_STALE").json()
    assert resp2["confidence_score"] < 0.7
    assert "Medium confidence" in resp2["confidence_label"]


# ── Edge Case 4: Customer Declines Confirmation ───────────────────────────────
def test_customer_declines_confirmation():
    """Customer declines: note stays at DRIVER_LOGGED tier."""
    client.post("/addresses", json={"address_id": "ADDR_CUST", "raw_text": "123 Cust Rd", "area": "apartment"})
    n = client.post("/notes", json={"address_id": "ADDR_CUST", "instruction_text": "Call at gate", "source": "DRIVER_LOGGED"}).json()

    # No confirm call — customer did not respond
    resp = client.get("/dispatch/ADDR_CUST").json()
    assert resp["note"]["source"] == "DRIVER_LOGGED"
    assert resp["note"]["confirmation_count"] == 1


# ── Edge Case 5: Address Key Collision ────────────────────────────────────────
def test_address_key_collision():
    """Address key collision: fail safe — near-duplicates stay separate."""
    addr1 = "Flat 4B, Green Apts"
    addr2 = "4-B Green Apartments"

    id1 = normalize_address(addr1)
    id2 = normalize_address(addr2)

    # Near-duplicates with different forms should NOT be merged by naive normalizer
    assert id1 != id2, "Near-duplicate addresses should remain separate (fail safe)"

    # True duplicates should merge correctly
    addr3 = "flat 4b green apts"
    id3 = normalize_address(addr3)
    assert id1 == id3, "True duplicates (case/punct only) should hash to same ID"


# ── Edge Case 6: Human-in-the-loop Duplicate Merge Review ─────────────────────
def test_duplicate_merge_requires_explicit_decision():
    """
    Case #6: A flagged duplicate pair must NOT be merged until ops explicitly decides.
    After a KEPT_SEPARATE decision, the pair does not re-flag on next flag scan.
    """
    # Create two addresses with high string similarity
    resp_a = client.post("/addresses", json={
        "address_id": "ADDR_DUP_A",
        "raw_text": "Flat 12B Tower Gardens",
        "area": "apartment"
    })
    assert resp_a.status_code == 201

    resp_b = client.post("/addresses", json={
        "address_id": "ADDR_DUP_B",
        "raw_text": "12B Tower Gardens Flat",
        "area": "apartment"
    })
    assert resp_b.status_code == 201

    # Check that the pair was auto-flagged as a potential duplicate
    dupes_resp = client.get("/duplicates/flag?pending_only=true")
    assert dupes_resp.status_code == 200
    dupes = dupes_resp.json()

    # Find our pair
    our_pair = next(
        (d for d in dupes
         if {d["addr_id_a"], d["addr_id_b"]} == {"ADDR_DUP_A", "ADDR_DUP_B"}),
        None
    )

    # ---- INVARIANT 1: flagged but NOT yet merged ----
    assert our_pair is not None, "Pair should be flagged automatically"
    assert our_pair["decision"] is None, "Pair must have NO decision yet — not auto-merged"

    # Both addresses should still be independently addressable
    resp_dispatch_a = client.get("/dispatch/ADDR_DUP_A")
    resp_dispatch_b = client.get("/dispatch/ADDR_DUP_B")
    assert resp_dispatch_a.status_code == 200
    assert resp_dispatch_b.status_code == 200

    log_id = our_pair["log_id"]

    # ---- INVARIANT 2: ops decides KEPT_SEPARATE ----
    decision_resp = client.post(
        f"/duplicates/{log_id}/decide",
        json={"decision": "KEPT_SEPARATE", "decided_by": "OPS_MANAGER_TEST"}
    )
    assert decision_resp.status_code == 200
    decision_data = decision_resp.json()
    assert decision_data["decision"] == "KEPT_SEPARATE"
    assert decision_data["decided_by"] == "OPS_MANAGER_TEST"

    # ---- INVARIANT 3: pair no longer appears in pending list ----
    pending_resp = client.get("/duplicates/flag?pending_only=true")
    pending = pending_resp.json()
    re_flagged = any(
        {d["addr_id_a"], d["addr_id_b"]} == {"ADDR_DUP_A", "ADDR_DUP_B"}
        for d in pending
    )
    assert not re_flagged, "Decided pair must NOT re-appear in pending list"

    # ---- INVARIANT 4: can't re-decide the same pair ----
    re_decision = client.post(
        f"/duplicates/{log_id}/decide",
        json={"decision": "MERGED", "decided_by": "OPS_MANAGER_TEST", "canonical_id": "ADDR_DUP_A"}
    )
    assert re_decision.status_code == 409, "Second decision on same pair should be rejected (409 Conflict)"


def test_merge_decision_preserves_history():
    """
    When MERGED: archived address gets canonical_id set, notes/attempts are preserved.
    Archived address is no longer returned by explorer.
    """
    client.post("/addresses", json={
        "address_id": "ADDR_MERGE_KEEP",
        "raw_text": "Block 5 Prestige Terrace Bangalore",
        "area": "apartment"
    })
    client.post("/addresses", json={
        "address_id": "ADDR_MERGE_DROP",
        "raw_text": "Prestige Terrace Block 5 Bangalore",
        "area": "apartment"
    })

    # Add a note to the to-be-archived address
    n_resp = client.post("/notes", json={
        "address_id": "ADDR_MERGE_DROP",
        "instruction_text": "Left entrance near parking",
        "source": "DRIVER_LOGGED"
    })
    assert n_resp.status_code == 201

    # Find the duplicate log entry
    dupes = client.get("/duplicates/flag?pending_only=true").json()
    our_pair = next(
        (d for d in dupes
         if {d["addr_id_a"], d["addr_id_b"]} == {"ADDR_MERGE_KEEP", "ADDR_MERGE_DROP"}),
        None
    )
    assert our_pair is not None, "High-similarity pair must be flagged"

    log_id = our_pair["log_id"]

    # Merge ADDR_MERGE_DROP into ADDR_MERGE_KEEP
    decision_resp = client.post(
        f"/duplicates/{log_id}/decide",
        json={
            "decision": "MERGED",
            "decided_by": "OPS_MANAGER_TEST",
            "canonical_id": "ADDR_MERGE_KEEP"
        }
    )
    assert decision_resp.status_code == 200
    data = decision_resp.json()
    assert data["canonical_id"] == "ADDR_MERGE_KEEP"

    # Archived address must NOT appear in active explorer
    explorer = client.get("/explorer").json()
    active_ids = {item["address_id"] for item in explorer}
    assert "ADDR_MERGE_DROP" not in active_ids, "Archived address must not appear in explorer"

    # But history must still be accessible (audit trail preserved)
    history = client.get("/history/ADDR_MERGE_DROP").json()
    assert history["notes"][0]["instruction_text"] == "Left entrance near parking", \
        "Note history on archived address must be preserved"


def test_input_validation_rejects_bad_address():
    """Input validation: empty raw_text should be rejected."""
    resp = client.post("/addresses", json={
        "address_id": "ADDR_BAD",
        "raw_text": "",
        "area": "apartment"
    })
    assert resp.status_code == 422, "Empty raw_text should fail validation"


def test_input_validation_rejects_bad_note():
    """Input validation: too-short instruction_text should be rejected."""
    client.post("/addresses", json={"address_id": "ADDR_NOTE_VAL", "raw_text": "Valid Text", "area": "apartment"})
    resp = client.post("/notes", json={
        "address_id": "ADDR_NOTE_VAL",
        "instruction_text": "Hi",  # too short
        "source": "DRIVER_LOGGED"
    })
    assert resp.status_code == 422, "Short instruction text should fail validation"


def test_rate_limit_on_confirmations():
    """Rate guard: same driver cannot spam confirmations for same note."""
    client.post("/addresses", json={"address_id": "ADDR_RATE", "raw_text": "Rate Limit Test St", "area": "apartment"})
    n = client.post("/notes", json={
        "address_id": "ADDR_RATE",
        "instruction_text": "Press intercom 204",
        "source": "DRIVER_LOGGED"
    }).json()

    # Make 3 confirms quickly (at limit)
    for _ in range(3):
        r = client.post(f"/notes/{n['note_id']}/confirm?source=DRIVER_LOGGED&driver_id=DRIVER_SPAM")
        assert r.status_code == 200

    # 4th confirm should be rate-limited
    r4 = client.post(f"/notes/{n['note_id']}/confirm?source=DRIVER_LOGGED&driver_id=DRIVER_SPAM")
    assert r4.status_code == 429, f"Expected 429 rate limit, got {r4.status_code}"


# ── ML Risk Score: No False Precision Guarantee ──────────────────────────────
def test_risk_score_no_false_precision():
    """
    ML Component Guarantee:
    Assert risk-score endpoint never returns bare unrounded floats or false precision.
    Must be rounded to nearest 0.05 (at most 2 decimal places),
    must be accompanied by explanatory model_note and disclaimer,
    and must keep confidence_band strictly separate.
    """
    client.post("/addresses", json={
        "address_id": "ADDR_ML_TEST",
        "raw_text": "Flat 402, Sai Apartments, 2nd Cross, Anna Nagar, Chennai - 600040",
        "area": "apartment"
    })

    resp = client.get("/dispatch/ADDR_ML_TEST/risk-score")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()

    score = data["model_risk_score"]
    assert isinstance(score, float)
    # Check precision: score * 20 should be an integer (e.g. 0.20, 0.25, 0.30, 0.35)
    rounded_check = round(score * 20.0)
    assert abs(score - (rounded_check / 20.0)) < 1e-5, f"Score {score} not rounded to nearest 0.05 (5%)"

    # Check that score string representation has at most 2 decimal places
    str_val = f"{score:.4f}".rstrip("0").rstrip(".")
    dec_places = len(str_val.split(".")[1]) if "." in str_val else 0
    assert dec_places <= 2, f"Score {score} has {dec_places} decimal places, expected at most 2"

    # Check required explanatory and boundary notes
    assert "model_note" in data
    assert "Statistical estimate" in data["model_note"]
    assert "not a substitute" in data["model_note"]

    assert "disclaimer" in data
    assert "Ops planning only" in data["disclaimer"]

    # Ensure rule-based confidence band is kept strictly separate
    assert "confidence_band" in data
    assert data["confidence_band"] in ["None", "Low", "Medium", "High"]

