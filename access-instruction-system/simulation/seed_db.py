import os
import sys
import pandas as pd
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from backend.database import SessionLocal, engine, Base
from backend import models

def seed_database():
    print("Seeding database with synthetic addresses and initial access notes...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    addresses_csv = os.path.join(os.path.dirname(__file__), "synthetic_addresses.csv")
    if not os.path.exists(addresses_csv):
        print("synthetic_addresses.csv not found. Generating data first...")
        from generate_data import generate_synthetic_data
        generate_synthetic_data()
        
    addresses_df = pd.read_csv(addresses_csv)
    
    addresses_added = 0
    notes_added = 0
    
    for _, row in addresses_df.iterrows():
        # Check if address exists
        existing_addr = db.query(models.Address).filter(models.Address.address_id == row["address_id"]).first()
        if not existing_addr:
            addr = models.Address(
                address_id=row["address_id"],
                raw_text=row["raw_text"],
                area=row["area"]
            )
            db.add(addr)
            addresses_added += 1
            
            # Create an initial high/medium confidence note for each address using true_instruction
            note = models.AccessNote(
                address_id=row["address_id"],
                instruction_text=row["true_instruction"],
                source=models.SourceEnum.DRIVER_LOGGED,
                created_at=datetime.utcnow(),
                last_confirmed_at=datetime.utcnow(),
                confirmation_count=3, # Gives high initial confidence (~0.80)
                contradiction_count=0
            )
            db.add(note)
            notes_added += 1
            
    db.commit()
    db.close()
    print(f"Successfully seeded {addresses_added} addresses and {notes_added} access notes into access_system.db!")

if __name__ == "__main__":
    seed_database()
