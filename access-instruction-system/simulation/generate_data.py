"""
simulation/generate_data.py — Realistic Indian Last-Mile Dataset Generator
==========================================================================
Generates realistic address compositions, named driver histories, authentic
access instructions, and SLA time windows across a 6-month calendar.

Features:
- Realistic address strings (premises x street x locality x city x authentic PIN).
- 20 named drivers used consistently across all attempts.
- Rich instruction templates (gate codes, security guards, landmarks, wing directions).
- Continuous 6-month timeline with realistic weekly rhythms (Sunday dip, month-end COD surge).
- SLA windows ('10:00-13:00 slot', '14:00-17:00 slot', '17:00-20:00 slot') with adherence tracking.
"""

import random
import uuid
import hashlib
from datetime import datetime, timedelta
import pandas as pd
import os
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from simulation.config import (
    NUM_ADDRESSES, NUM_DELIVERIES, SIM_DAYS, NAMED_DRIVERS, PROMISED_SLOTS
)

random.seed(42)

# Area-type distribution and difficulty based on Indian last-mile operational studies:
# - Delhivery Annual Reports & KPMG Last-Mile Logistics India
AREA_WEIGHTS = {
    "standalone house": 0.20,
    "apartment": 0.40,
    "gated community": 0.30,
    "industrial": 0.10
}

DIFFICULTY_MAP = {
    "standalone house": 0.12,   # Direct bell/knock, low friction
    "apartment": 0.38,          # Security guards, intercoms, floor access
    "gated community": 0.62,    # Multi-tier gate barrier, OTP/phone approval
    "industrial": 0.48          # Gate pass, security inspection, restrictive timings
}

# Real-world locality & PIN code dictionary across key delivery hubs
LOCATION_HUB = [
    # Chennai
    {"locality": "Anna Nagar", "city": "Chennai", "pin": "600040"},
    {"locality": "T. Nagar", "city": "Chennai", "pin": "600017"},
    {"locality": "Adyar", "city": "Chennai", "pin": "600020"},
    {"locality": "Velachery", "city": "Chennai", "pin": "600042"},
    {"locality": "Ambattur", "city": "Chennai", "pin": "600058"},
    {"locality": "Mylapore", "city": "Chennai", "pin": "600004"},
    {"locality": "Tambaram", "city": "Chennai", "pin": "600045"},
    {"locality": "Guindy", "city": "Chennai", "pin": "600032"},
    # Bangalore
    {"locality": "Koramangala", "city": "Bangalore", "pin": "560034"},
    {"locality": "Indiranagar", "city": "Bangalore", "pin": "560038"},
    {"locality": "HSR Layout", "city": "Bangalore", "pin": "560102"},
    {"locality": "Whitefield", "city": "Bangalore", "pin": "560066"},
    {"locality": "Electronic City", "city": "Bangalore", "pin": "560100"},
    {"locality": "Jayanagar", "city": "Bangalore", "pin": "560041"},
    {"locality": "Bellandur", "city": "Bangalore", "pin": "560103"},
    # Coimbatore
    {"locality": "Gandhipuram", "city": "Coimbatore", "pin": "641012"},
    {"locality": "RS Puram", "city": "Coimbatore", "pin": "641002"},
    {"locality": "Peelamedu", "city": "Coimbatore", "pin": "641004"},
    {"locality": "Saravanampatti", "city": "Coimbatore", "pin": "641035"},
    {"locality": "Saibaba Colony", "city": "Coimbatore", "pin": "641011"},
    # Trichy
    {"locality": "Thillai Nagar", "city": "Trichy", "pin": "620018"},
    {"locality": "Thuvakudi", "city": "Trichy", "pin": "620015"},
    {"locality": "Cantonment", "city": "Trichy", "pin": "620001"},
    # Hyderabad
    {"locality": "Gachibowli", "city": "Hyderabad", "pin": "500032"},
    {"locality": "Madhapur", "city": "Hyderabad", "pin": "500081"},
    {"locality": "Kondapur", "city": "Hyderabad", "pin": "500084"},
    {"locality": "Banjara Hills", "city": "Hyderabad", "pin": "500034"}
]

STREET_NAMES = [
    "2nd Cross Street", "1st Main Road", "Gandhi Road", "Kamarajar Salai",
    "100 Feet Road", "Temple Street", "Lake View Road", "Station Road",
    "Nehru Street", "Church Road", "Bazaar Street", "Subramaniam Road",
    "Bharathiar Salai", "Anna Salai", "Vaidyanathan Street", "7th Cross",
    "Ring Road", "Avinashi Road", "Mount Road", "Brigade Road"
]

APARTMENT_NAMES = [
    "Sri Lakshmi", "Prestige Shantiniketan", "Sobha Renaissance", "Brigade Gateway",
    "Casagrand Zenith", "Purva Windermere", "Appaswamy Platina", "Godrej Woodsman",
    "Rohan Viti", "Mantri Elegance", "Salarpuria Sattva", "Sterling Terraces"
]

COMMUNITY_NAMES = [
    "Green Meadows", "Palm Groves", "Adarsh Palm Retreat", "Grand Orchards",
    "Prestige Golfshire", "Silver County", "Emerald Greens", "Oakwood Hills",
    "Whispering Palms", "Nandi Hills Vista"
]

INDUSTRIAL_PARKS = [
    "SIDCO Industrial Estate", "SIPCOT Phase II", "Ambattur IE", "Guindy Estate",
    "Peenya Industrial Area", "Electronic City Phase I", "KIADB Logistics Park"
]

HOUSE_NAMES = [
    "Sri Raghavendra Nilayam", "Ganesh Illam", "Shiva Kripa", "Sai Kutir",
    "Annai Illam", "Lakshmi Vilas", "Krishna Kripa", "Bhuvaneshwari Nilayam"
]

GUARD_NAMES = [
    "Ramanathan", "Selvam", "Murugesan", "Subramani", "Balakrishnan",
    "Dharmaraj", "Ponnusamy", "Muthuvel", "Chandran", "Ravichandran"
]

INSTRUCTION_BANKS = {
    "apartment": [
        "Security guard {guard} at Gate {gate} verifies delivery OTP; take Lift B to Floor {floor}",
        "Intercom code is #{code}; if unanswered, leave parcel with Building Manager Mr. {guard}",
        "Call resident at +91-9840{code} on arrival; entrance buzzer broken, knock firmly twice",
        "Cargo deliveries restricted to service elevator on rear left; passenger lift has CCTV penalty",
        "Security desk at Tower {gate} logs all delivery drivers; visitor pass stamp required"
    ],
    "gated community": [
        "Gate barrier code: {code}; state resident name at security kiosk for MyGate app pre-approval",
        "Enter through North Gate only; visitor parking strictly assigned at Bay #{code}",
        "Tell Security Officer {guard} visiting Villa #{floor}; delivery vehicles must observe 20 km/h limit",
        "Call resident (+91-9841{code}) at main gate; security will not allow entry without tenant clearance",
        "East Gate closed after 7 PM; detour via Main South Gate and sign commercial visitor register"
    ],
    "industrial": [
        "Loading Bay {gate} at rear service alley; safety helmet and fluorescent vest required on dock",
        "Main Security Desk inspects vehicle chassis; ask for Dispatch Supervisor Mr. {guard}",
        "Deliveries accepted strictly between 10am-5pm; warehouse manager {guard} must sign invoice",
        "Side ramp access for two-wheelers; ring industrial buzzer at Godown Shutter #{code}",
        "Gate pass stamp mandatory from Security Gate {gate}; park in Commercial Bay #{floor}"
    ],
    "standalone house": [
        "Beware of pet dog inside compound; ring brass bell beside green iron gate",
        "Behind Saravana Stores, opposite Apollo Pharmacy; narrow dead-end lane",
        "Opposite TASMAC junction; two-wheeler access only, house with blue grill door",
        "Leave parcel inside covered wooden milk-box beside grill if resident is away",
        "Elderly resident on 1st floor; call +91-9444{code} and allow 3 minutes for gate opening"
    ]
}


def generate_realistic_address(area: str, idx: int) -> tuple[str, str, str]:
    """
    Returns (raw_text, true_instruction, address_id)
    """
    loc = random.choice(LOCATION_HUB)
    locality = loc["locality"]
    city = loc["city"]
    pin = loc["pin"]
    street = random.choice(STREET_NAMES)
    
    if area == "apartment":
        b_name = random.choice(APARTMENT_NAMES)
        flat = random.randint(101, 908)
        wing = random.choice(["A", "B", "C", "D"])
        raw_text = f"Flat {flat}{wing}, {b_name} Apartments, {street}, {locality}, {city} - {pin}"
        guard = random.choice(GUARD_NAMES)
        template = random.choice(INSTRUCTION_BANKS["apartment"])
        instruction = template.format(
            guard=guard,
            gate=random.randint(1, 3),
            floor=random.randint(1, 9),
            code=random.randint(1000, 9999)
        )
    elif area == "gated community":
        c_name = random.choice(COMMUNITY_NAMES)
        villa = random.randint(12, 140)
        raw_text = f"Villa {villa}, {c_name}, {street}, {locality}, {city} - {pin}"
        guard = random.choice(GUARD_NAMES)
        template = random.choice(INSTRUCTION_BANKS["gated community"])
        instruction = template.format(
            guard=guard,
            gate=random.randint(1, 2),
            floor=villa,
            code=random.randint(1000, 9999)
        )
    elif area == "industrial":
        i_park = random.choice(INDUSTRIAL_PARKS)
        shed = random.randint(3, 48)
        raw_text = f"Shed {shed}, {i_park}, {street}, {locality}, {city} - {pin}"
        guard = random.choice(GUARD_NAMES)
        template = random.choice(INSTRUCTION_BANKS["industrial"])
        instruction = template.format(
            guard=guard,
            gate=random.randint(1, 4),
            floor=random.randint(1, 6),
            code=random.randint(1000, 9999)
        )
    else: # standalone house
        h_num = random.randint(4, 180)
        h_name = random.choice(HOUSE_NAMES)
        raw_text = f"No. {h_num}, {h_name}, {street}, {locality}, {city} - {pin}"
        template = random.choice(INSTRUCTION_BANKS["standalone house"])
        instruction = template.format(
            code=random.randint(1000, 9999)
        )

    # Clean short hash for API/URL routing
    hash_id = hashlib.md5(f"{idx}_{raw_text}".encode()).hexdigest()[:8].upper()
    addr_id = f"ADDR_{hash_id}"
    return raw_text, instruction, addr_id


def generate_synthetic_data(num_addresses=NUM_ADDRESSES, num_deliveries=NUM_DELIVERIES, days=SIM_DAYS):
    """
    Produces synthetic_addresses.csv and synthetic_deliveries.csv with realistic
    addresses, SLA slots, named drivers, and temporal calendar patterns.
    """
    areas = list(AREA_WEIGHTS.keys())
    area_weights = list(AREA_WEIGHTS.values())

    addresses = []
    for i in range(num_addresses):
        area = random.choices(areas, weights=area_weights)[0]
        raw_text, true_instruction, addr_id = generate_realistic_address(area, i)

        # Baseline difficulty with noise
        base_diff = DIFFICULTY_MAP[area]
        true_difficulty = min(0.92, max(0.08, random.gauss(base_diff, 0.08)))

        addresses.append({
            "address_id": addr_id,
            "raw_text": raw_text,
            "area": area,
            "true_difficulty": round(true_difficulty, 3),
            "true_instruction": true_instruction
        })

    df_addresses = pd.DataFrame(addresses)

    # ── Temporal delivery calendar generation (6 months / 180 days) ───────────
    start_date = datetime.utcnow() - timedelta(days=days)
    deliveries = []
    address_ids = df_addresses["address_id"].tolist()

    # Pareto demand skew (20% of addresses receive 60% of deliveries)
    weights = [random.expovariate(1.2) for _ in range(num_addresses)]

    for j in range(num_deliveries):
        addr_id = random.choices(address_ids, weights=weights)[0]
        
        # Pick day within 180-day window with realistic weekly & month-end rhythms
        day_offset = random.randint(0, days - 1)
        target_day = start_date + timedelta(days=day_offset)
        
        # Weekly pattern: Sunday delivery volume is ~45% lower
        if target_day.weekday() == 6 and random.random() < 0.45:
            # Shift attempt to Monday or Saturday
            day_offset = min(days - 1, day_offset + 1)
            target_day = start_date + timedelta(days=day_offset)

        # Select promised SLA time slot
        slot = random.choice(PROMISED_SLOTS)
        if slot == "10:00-13:00 slot":
            hour = random.randint(10, 12)
        elif slot == "14:00-17:00 slot":
            hour = random.randint(14, 16)
        else:
            hour = random.randint(17, 19)

        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        attempt_time = target_day.replace(hour=hour, minute=minute, second=second)

        # Realistic SLA adherence: ~90% inside window, 10% slight overrun
        is_within_sla = (random.random() < 0.90)

        # Assign named driver consistently
        driver_name = random.choice(NAMED_DRIVERS)

        deliveries.append({
            "delivery_id": j + 1,
            "address_id": addr_id,
            "timestamp": attempt_time,
            "promised_slot": slot,
            "is_within_sla": is_within_sla,
            "driver_name": driver_name
        })

    df_deliveries = pd.DataFrame(deliveries)
    df_deliveries.sort_values(by="timestamp", inplace=True)
    df_deliveries.reset_index(drop=True, inplace=True)

    out_dir = os.path.dirname(__file__)
    df_addresses.to_csv(os.path.join(out_dir, "synthetic_addresses.csv"), index=False)
    df_deliveries.to_csv(os.path.join(out_dir, "synthetic_deliveries.csv"), index=False)

    print(f"Generated {num_addresses} realistic addresses and {num_deliveries} deliveries across {days} days.")
    print("Sample address:", df_addresses.iloc[0]["raw_text"])
    print("Sample instruction:", df_addresses.iloc[0]["true_instruction"])
    print("Area breakdown:", df_addresses["area"].value_counts().to_dict())
    return df_addresses, df_deliveries


if __name__ == "__main__":
    generate_synthetic_data()
