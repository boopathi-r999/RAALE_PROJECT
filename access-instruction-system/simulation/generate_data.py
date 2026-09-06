import random
import uuid
from datetime import datetime, timedelta
import pandas as pd
import os

random.seed(42)

def generate_synthetic_data(num_addresses=200, num_deliveries=1000, days=90):
    areas = ["apartment", "gated community", "industrial", "standalone house"]
    
    # Difficulty base probabilities (failure rate without note)
    difficulty_map = {
        "standalone house": 0.1,
        "apartment": 0.35,
        "industrial": 0.45,
        "gated community": 0.6
    }
    
    instructions_templates = {
        "standalone house": ["Beware of dog", "Leave at back porch", "Call upon arrival"],
        "apartment": ["Call {name} at security", "Leave with building manager", "Code is {code}"],
        "industrial": ["Deliver to loading dock B", "Enter via side gate", "Ask for warehouse manager"],
        "gated community": ["Gate code: {code}", "Security needs flat number, ask for {name}", "Entry from North Gate only"]
    }
    
    addresses = []
    
    # Generate addresses
    for i in range(num_addresses):
        area = random.choices(areas, weights=[0.4, 0.3, 0.1, 0.2])[0]
        addr_id = f"ADDR_{uuid.uuid4().hex[:8].upper()}"
        
        # Base true difficulty with some noise
        base_diff = difficulty_map[area]
        true_difficulty = min(0.95, max(0.05, random.gauss(base_diff, 0.1)))
        
        template = random.choice(instructions_templates[area])
        code = str(random.randint(1000, 9999))
        name = random.choice(["Ramesh", "Suresh", "Priya", "Anita"])
        true_instruction = template.format(code=code, name=name)
        
        raw_text = f"{i+1} Main St, {area.title()} Zone"
        
        addresses.append({
            "address_id": addr_id,
            "raw_text": raw_text,
            "area": area,
            "true_difficulty": round(true_difficulty, 3),
            "true_instruction": true_instruction
        })
        
    df_addresses = pd.DataFrame(addresses)
    
    # Generate delivery arrivals sequence
    start_date = datetime.utcnow() - timedelta(days=days)
    
    deliveries = []
    # To simulate repeat deliveries to same hard addresses, we use a Pareto-like distribution or just weights
    # We will pick addresses with some bias (e.g. some people order more).
    address_ids = df_addresses["address_id"].tolist()
    weights = [random.expovariate(1.0) for _ in range(num_addresses)]
    
    for j in range(num_deliveries):
        addr_id = random.choices(address_ids, weights=weights)[0]
        # Random time within the window
        seconds_offset = random.randint(0, days * 86400)
        timestamp = start_date + timedelta(seconds=seconds_offset)
        
        deliveries.append({
            "delivery_id": j + 1,
            "address_id": addr_id,
            "timestamp": timestamp
        })
        
    df_deliveries = pd.DataFrame(deliveries)
    df_deliveries.sort_values(by="timestamp", inplace=True)
    df_deliveries.reset_index(drop=True, inplace=True)
    
    os.makedirs(os.path.dirname(__file__), exist_ok=True)
    df_addresses.to_csv(os.path.join(os.path.dirname(__file__), "synthetic_addresses.csv"), index=False)
    df_deliveries.to_csv(os.path.join(os.path.dirname(__file__), "synthetic_deliveries.csv"), index=False)
    print(f"Generated {num_addresses} addresses and {num_deliveries} delivery arrivals.")

if __name__ == "__main__":
    generate_synthetic_data()
