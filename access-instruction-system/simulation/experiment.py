import pandas as pd
import numpy as np
import random
import os
from fastapi.testclient import TestClient
import matplotlib.pyplot as plt

import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from backend.main import app
from backend.database import Base, engine, get_db
from sqlalchemy.orm import sessionmaker

# Create a fresh database for each simulation run
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

client = TestClient(app)

COST_PER_ATTEMPT = 40.0
EMISSION_G_CO2_PER_KM = 120.0
AVG_KM_PER_ATTEMPT = 3.5

def run_simulation(mode="prototype"):
    reset_db()
    
    addresses = pd.read_csv(os.path.join(os.path.dirname(__file__), "synthetic_addresses.csv"))
    deliveries = pd.read_csv(os.path.join(os.path.dirname(__file__), "synthetic_deliveries.csv"))
    
    # Pre-populate addresses in DB
    for _, row in addresses.iterrows():
        client.post("/addresses", json={
            "address_id": row["address_id"],
            "raw_text": row["raw_text"],
            "area": row["area"]
        })
        
    true_instructions = dict(zip(addresses.address_id, addresses.true_instruction))
    true_difficulties = dict(zip(addresses.address_id, addresses.true_difficulty))
    
    outcomes_log = []
    
    # We will flip the ground truth instruction for some addresses halfway to test stale note decay
    halfway_point = len(deliveries) // 2
    
    for idx, row in deliveries.iterrows():
        if idx == halfway_point:
            # Change ground truth for 20% of addresses
            keys_to_change = random.sample(list(true_instructions.keys()), int(len(true_instructions) * 0.2))
            for k in keys_to_change:
                true_instructions[k] = true_instructions[k] + " (CHANGED)"

        addr_id = row["address_id"]
        t_difficulty = true_difficulties[addr_id]
        t_instruction = true_instructions[addr_id]
        
        note_used = None
        confidence_label = None
        confidence_score = None
        
        if mode == "prototype":
            # 1. Dispatch
            resp = client.get(f"/dispatch/{addr_id}").json()
            note_used = resp.get("note")
            confidence_label = resp.get("confidence_label")
            confidence_score = resp.get("confidence_score")
            
            if note_used:
                # Is the note correct?
                is_correct = (note_used["instruction_text"] == t_instruction)
                if is_correct:
                    # High chance of success with correct note
                    p_fail = 0.05
                else:
                    # High chance of failure with wrong/stale note
                    p_fail = 0.95
            else:
                p_fail = t_difficulty
        else:
            # Baseline: no memory
            p_fail = t_difficulty
            
        # Determine outcome
        if random.random() < p_fail:
            # Failure. 20% chance it's RTO, 80% FAILED
            outcome_val = "RTO" if random.random() < 0.2 else "FAILED"
            reason = "NO_ACCESS"
        else:
            outcome_val = "SUCCESS"
            reason = "NONE"
            
        # Log outcome
        attempt_payload = {
            "address_id": addr_id,
            "outcome": outcome_val,
            "failure_reason": reason,
            "driver_id": f"DRIVER_{random.randint(1,50)}"
        }
        if note_used:
            attempt_payload["used_note_id"] = note_used["note_id"]
            
        client.post("/attempts", json=attempt_payload)
        
        # If success and no note, driver adds note (prototype only)
        if mode == "prototype" and outcome_val == "SUCCESS" and not note_used:
            # 90% driver logs true instruction, 10% they typo it
            if random.random() < 0.9:
                driver_note = t_instruction
            else:
                driver_note = "Typo: " + t_instruction
                
            client.post("/notes", json={
                "address_id": addr_id,
                "instruction_text": driver_note,
                "source": "DRIVER_LOGGED"
            })
            
        # Optional: Customer confirms note randomly (simulated)
        if mode == "prototype" and random.random() < 0.02 and note_used:
            client.post(f"/notes/{note_used['note_id']}/confirm?source=CUSTOMER_CONFIRMED")
            
        outcomes_log.append({
            "delivery_id": row["delivery_id"],
            "address_id": addr_id,
            "outcome": outcome_val,
            "used_note": bool(note_used),
            "confidence_score": confidence_score
        })
        
    return pd.DataFrame(outcomes_log)

def calculate_metrics(df):
    total_attempts = len(df)
    successes = len(df[df["outcome"] == "SUCCESS"])
    rto = len(df[df["outcome"] == "RTO"])
    
    # Repeat failure rate
    # group by address, find failed attempts after the first failure
    repeat_failures = 0
    total_attempts_at_problem_addresses = 0
    
    for addr, group in df.groupby("address_id"):
        # find index of first failure
        fails = group[group["outcome"].isin(["FAILED", "RTO"])]
        if len(fails) > 0:
            first_fail_idx = fails.index[0]
            subsequent_attempts = group.loc[first_fail_idx+1:]
            total_attempts_at_problem_addresses += len(subsequent_attempts)
            repeat_failures += len(subsequent_attempts[subsequent_attempts["outcome"].isin(["FAILED", "RTO"])])
            
    repeat_failure_rate = repeat_failures / total_attempts_at_problem_addresses if total_attempts_at_problem_addresses > 0 else 0
    reliability = successes / total_attempts
    cost_per_success = (total_attempts * COST_PER_ATTEMPT) / successes if successes > 0 else 0
    emissions = total_attempts * AVG_KM_PER_ATTEMPT * EMISSION_G_CO2_PER_KM
    rto_rate = rto / total_attempts
    
    return {
        "Repeat Failure Rate": f"{repeat_failure_rate:.1%}",
        "Reliability": f"{reliability:.1%}",
        "Cost per Success": f"Rs.{cost_per_success:.2f}",
        "Emissions (kg CO2)": f"{emissions / 1000:.1f} kg",
        "RTO Rate": f"{rto_rate:.1%}"
    }

def main():
    print("Running Baseline Simulation...")
    df_base = run_simulation("baseline")
    print("Running Prototype Simulation...")
    df_proto = run_simulation("prototype")
    
    metrics_base = calculate_metrics(df_base)
    metrics_proto = calculate_metrics(df_proto)
    
    print("\n--- RESULTS ---")
    print(f"{'Metric':<25} | {'Baseline':<15} | {'Prototype':<15}")
    print("-" * 60)
    for k in metrics_base.keys():
        print(f"{k:<25} | {metrics_base[k]:<15} | {metrics_proto[k]:<15}")
        
    # Plotting
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(__file__)), "evaluation"), exist_ok=True)
    
    labels = list(metrics_base.keys())
    
    # We will just plot Reliability and RTO Rate
    vals_b = [float(metrics_base["Reliability"].strip('%')), float(metrics_base["RTO Rate"].strip('%'))]
    vals_p = [float(metrics_proto["Reliability"].strip('%')), float(metrics_proto["RTO Rate"].strip('%'))]
    
    x = np.arange(2)
    width = 0.35
    fig, ax = plt.subplots()
    ax.bar(x - width/2, vals_b, width, label='Baseline')
    ax.bar(x + width/2, vals_p, width, label='Prototype')
    ax.set_ylabel('Percentage')
    ax.set_title('Baseline vs Prototype (Reliability & RTO)')
    ax.set_xticks(x)
    ax.set_xticklabels(['Reliability (%)', 'RTO Rate (%)'])
    ax.legend()
    
    plt.savefig(os.path.join(os.path.dirname(os.path.dirname(__file__)), "evaluation", "chart_metrics.png"))
    print("\nSaved chart to evaluation/chart_metrics.png")
    
if __name__ == "__main__":
    main()
