"""
simulation/seed_db.py — Database Seeder with Realistic Indian Addresses & Delivery History
========================================================================================
Seeds SQLite (access_system.db) with:
1. 400 realistic Indian addresses across Chennai, Bangalore, Coimbatore, Trichy, Hyderabad.
2. Initial access notes with varying confidence tiers.
3. Realistic historical delivery attempts logged with named drivers, SLA slots, and outcomes.
"""

import os
import sys
import random
import pandas as pd
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from backend.database import SessionLocal, engine, Base
from backend import models

def seed_database(reset_all=True):
    print("Seeding database with realistic Indian addresses, notes, and attempt history...")
    
    if reset_all:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    addresses_csv = os.path.join(os.path.dirname(__file__), "synthetic_addresses.csv")
    deliveries_csv = os.path.join(os.path.dirname(__file__), "synthetic_deliveries.csv")
    
    if not os.path.exists(addresses_csv) or not os.path.exists(deliveries_csv):
        print("Dataset not found. Generating synthetic data first...")
        from simulation.generate_data import generate_synthetic_data
        generate_synthetic_data()
        
    addresses_df = pd.read_csv(addresses_csv)
    deliveries_df = pd.read_csv(deliveries_csv)
    
    addresses_added = 0
    notes_added = 0
    attempts_added = 0
    
    random.seed(42)
    
    note_map = {} # addr_id -> note_id
    
    for idx, row in addresses_df.iterrows():
        existing_addr = db.query(models.Address).filter(models.Address.address_id == row["address_id"]).first()
        if not existing_addr:
            addr = models.Address(
                address_id=row["address_id"],
                raw_text=row["raw_text"],
                area=row["area"]
            )
            db.add(addr)
            addresses_added += 1
            
            # Initial note distribution:
            # 80% addresses have an initial note with realistic confirmations
            # 20% remain cold-start (0 notes)
            if idx % 5 != 0:
                conf_count = random.choice([1, 2, 3, 4, 6])
                contra_count = 1 if (random.random() < 0.15) else 0
                days_ago = random.randint(1, 45)
                last_conf = datetime.utcnow() - timedelta(days=days_ago)
                
                note = models.AccessNote(
                    address_id=row["address_id"],
                    instruction_text=row["true_instruction"],
                    source=models.SourceEnum.DRIVER_LOGGED,
                    created_at=last_conf - timedelta(days=5),
                    last_confirmed_at=last_conf,
                    confirmation_count=conf_count,
                    contradiction_count=contra_count
                )
                db.add(note)
                db.flush()
                note_map[row["address_id"]] = note.note_id
                notes_added += 1
                
    db.commit()
    
    # Seed past delivery attempts (take first 1,500 deliveries from schedule to represent past history)
    past_deliveries = deliveries_df.head(1500)
    for _, del_row in past_deliveries.iterrows():
        addr_id = del_row["address_id"]
        used_nid = note_map.get(addr_id)
        
        # Determine outcome: if note exists, high success rate; if cold start, baseline difficulty
        addr_meta = addresses_df[addresses_df["address_id"] == addr_id]
        diff = addr_meta["true_difficulty"].values[0] if len(addr_meta) > 0 else 0.4
        
        if used_nid:
            fail_p = 0.12 if random.random() < 0.85 else 0.70
        else:
            fail_p = diff
            
        if random.random() < fail_p:
            outcome = models.OutcomeEnum.RTO if random.random() < 0.2 else models.OutcomeEnum.FAILED
            reason = random.choice([
                models.FailureReasonEnum.NO_ACCESS,
                models.FailureReasonEnum.GATE_LOCKED,
                models.FailureReasonEnum.CUSTOMER_UNAVAILABLE
            ])
        else:
            outcome = models.OutcomeEnum.SUCCESS
            reason = models.FailureReasonEnum.NONE
            
        ts_val = pd.to_datetime(del_row["timestamp"]).to_pydatetime()
        
        attempt = models.DeliveryAttempt(
            address_id=addr_id,
            timestamp=ts_val,
            outcome=outcome,
            failure_reason=reason,
            driver_id=str(del_row.get("driver_name", "R. Suresh")),
            used_note_id=used_nid,
            promised_slot=str(del_row.get("promised_slot", "10:00-13:00 slot")),
            is_within_sla=bool(del_row.get("is_within_sla", True))
        )
        db.add(attempt)
        attempts_added += 1

    db.commit()
    db.close()
    print(f"Successfully seeded {addresses_added} addresses, {notes_added} access notes, and {attempts_added} historical attempts into access_system.db!")

if __name__ == "__main__":
    seed_database()
