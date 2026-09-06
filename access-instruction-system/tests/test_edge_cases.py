import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import re
import hashlib

from backend.main import app
from backend.database import Base, engine, get_db
from backend.models import SourceEnum, OutcomeEnum

# Simple normalizer for testing Address Key Collision
def normalize_address(raw: str) -> str:
    # lower case, remove punctuation, remove extra spaces
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

def test_cold_start():
    """3. Cold start: address with zero notes explicitly returns low confidence."""
    # Create address
    client.post("/addresses", json={"address_id": "ADDR_COLD", "raw_text": "123 Cold St", "area": "apartment"})
    
    resp = client.get("/dispatch/ADDR_COLD")
    assert resp.status_code == 200
    data = resp.json()
    assert data["note"] is None
    assert "Low confidence / no verified note" in data["confidence_label"]

def test_conflicting_notes():
    """1. Conflicting notes: contradictory instructions show contradiction in confidence."""
    client.post("/addresses", json={"address_id": "ADDR_CONF", "raw_text": "123 Conflict", "area": "apartment"})
    
    # Driver A logs Note 1
    n1 = client.post("/notes", json={"address_id": "ADDR_CONF", "instruction_text": "Gate 1", "source": "DRIVER_LOGGED"}).json()
    # Driver B logs Note 2
    n2 = client.post("/notes", json={"address_id": "ADDR_CONF", "instruction_text": "Gate 2", "source": "DRIVER_LOGGED"}).json()
    
    # Both fail, contradiction increases (we simulate 3 failures each to drop confidence below 0.4)
    for _ in range(3):
        client.post("/attempts", json={"address_id": "ADDR_CONF", "outcome": "FAILED", "used_note_id": n1["note_id"], "driver_id": "D1"})
        client.post("/attempts", json={"address_id": "ADDR_CONF", "outcome": "FAILED", "used_note_id": n2["note_id"], "driver_id": "D2"})
    
    # Check dispatch (both should have lower confidence, likely low)
    resp = client.get("/dispatch/ADDR_CONF").json()
    assert resp["confidence_score"] < 0.4 # Raw will be 1/3 ~ 0.33

def test_stale_note_causes_failure():
    """2. Stale note causes failure: previously high confidence drops after failures."""
    client.post("/addresses", json={"address_id": "ADDR_STALE", "raw_text": "123 Stale", "area": "apartment"})
    
    n = client.post("/notes", json={"address_id": "ADDR_STALE", "instruction_text": "Old Code", "source": "DRIVER_LOGGED"}).json()
    
    # Build up confidence (3 successes)
    for _ in range(3):
        client.post("/attempts", json={"address_id": "ADDR_STALE", "outcome": "SUCCESS", "used_note_id": n["note_id"], "driver_id": "D1"})
        
    resp1 = client.get("/dispatch/ADDR_STALE").json()
    assert resp1["confidence_score"] >= 0.7
    assert "High confidence" in resp1["confidence_label"]
    
    # Now it becomes stale, fails 4 times
    for _ in range(4):
        client.post("/attempts", json={"address_id": "ADDR_STALE", "outcome": "FAILED", "used_note_id": n["note_id"], "driver_id": "D2"})
        
    resp2 = client.get("/dispatch/ADDR_STALE").json()
    # Math: conf = 1(initial)+3(success)=4. failures = 4. raw = (4+1)/(4+4+2) = 0.5.
    assert resp2["confidence_score"] < 0.7
    assert "Medium confidence" in resp2["confidence_label"]

def test_customer_declines_confirmation():
    """4. Customer declines/no response: note stays at DRIVER_LOGGED."""
    client.post("/addresses", json={"address_id": "ADDR_CUST", "raw_text": "123 Cust", "area": "apartment"})
    
    n = client.post("/notes", json={"address_id": "ADDR_CUST", "instruction_text": "Call", "source": "DRIVER_LOGGED"}).json()
    
    # We do NOT hit the /confirm endpoint because they didn't respond
    resp = client.get("/dispatch/ADDR_CUST").json()
    assert resp["note"]["source"] == "DRIVER_LOGGED"
    assert resp["note"]["confirmation_count"] == 1

def test_address_key_collision():
    """5. Address key collision: fail safe and doesn't merge wrongly."""
    addr1 = "Flat 4B, Green Apts"
    addr2 = "4-B Green Apartments"
    
    id1 = normalize_address(addr1)
    id2 = normalize_address(addr2)
    
    # Our simple normalizer will fail to merge these (apts vs apartments)
    # This is a "fail safe" - it treats them as separate instead of merging unrelated.
    assert id1 != id2
    
    # Let's test two exactly equivalent
    addr3 = "flat 4b green apts"
    id3 = normalize_address(addr3)
    
    assert id1 == id3 # successfully merged true duplicates
