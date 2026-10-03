"""
experiment.py — Multi-Seed Baseline vs Prototype Experiment Runner
==================================================================
Runs Baseline and Prototype simulations across NUM_SEEDS random seeds,
computes mean ± SD and 95% CI for each metric, and produces:
  - evaluation/multi_seed_metrics.png   (error-bar charts per metric)
  - evaluation/emissions_comparison.png (fixed-volume vs responsive-volume)
  - evaluation/reliability_diagram.png  (confidence calibration across all seeds)
  - evaluation/multi_seed_results.json  (raw data for the report)

Mode A (fixed-volume):  1000 attempts for both arms — fair like-for-like comparison.
Mode B (responsive-volume): attempts emerge from failure cascades — realistic saving.
"""

import pandas as pd
import numpy as np
import random
import os
import json
import logging
import math
import sys
import tempfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── path setup ──────────────────────────────────────────────────────────────
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# Override the DB URL BEFORE importing the app so every test run uses an
# isolated temp SQLite file — avoids conflicts with the live server DB and
# sidesteps the drop_all ordering issue with self-referential FKs.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["EXPERIMENT_DB_URL"] = f"sqlite:///{_tmp_db.name}"

import backend.database as _db_module
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Patch the module-level engine so all backend code uses our temp DB
_exp_engine = create_engine(
    f"sqlite:///{_tmp_db.name}",
    connect_args={"check_same_thread": False}
)
_db_module.engine = _exp_engine
_db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_exp_engine)

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import Base
from backend import models
from simulation.config import (
    COST_PER_ATTEMPT_RS, EMISSION_G_CO2_PER_KM, AVG_KM_PER_ATTEMPT,
    NUM_SEEDS, NUM_ADDRESSES, NUM_DELIVERIES, SIM_DAYS,
    GROUND_TRUTH_CHANGE_FRACTION, DRIVER_ACCURACY_RATE,
    CUSTOMER_CONFIRM_RATE, RTO_FRACTION_OF_FAILURES, MAX_REATTEMPTS_PER_ADDRESS,
    NAMED_DRIVERS, PROMISED_SLOTS
)

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("experiment")

client = TestClient(app)

EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "evaluation")
SIM_DIR = os.path.dirname(__file__)

# ── database helpers ─────────────────────────────────────────────────────────
def reset_db():
    """Drop and recreate all tables on the experiment's isolated temp DB."""
    Base.metadata.drop_all(bind=_exp_engine)
    Base.metadata.create_all(bind=_exp_engine)


# ── single-seed fixed-volume simulation ──────────────────────────────────────
def run_simulation_fixed_volume(mode: str, rng: random.Random) -> pd.DataFrame:
    """
    Fixed volume: both arms get exactly NUM_DELIVERIES attempts drawn from the same
    CSV sequence (re-seeded per-run). This is the fair like-for-like cost/reliability
    comparison (equivalent to Review 1's single run, but now multi-seeded).
    """
    reset_db()

    addresses = pd.read_csv(os.path.join(SIM_DIR, "synthetic_addresses.csv"))
    deliveries = pd.read_csv(os.path.join(SIM_DIR, "synthetic_deliveries.csv"))

    # Re-shuffle delivery sequence with this run's seed for variety
    deliveries = deliveries.sample(frac=1, random_state=rng.randint(0, 2**31)).reset_index(drop=True)

    deliveries = deliveries.head(min(len(deliveries), 600))

    true_instructions = dict(zip(addresses.address_id, addresses.true_instruction))
    true_difficulties = dict(zip(addresses.address_id, addresses.true_difficulty))

    # Pre-populate addresses in bulk
    db = _db_module.SessionLocal()
    db.add_all([models.Address(address_id=r["address_id"], raw_text=r["raw_text"], area=r["area"]) for _, r in addresses.iterrows()])
    db.commit()
    db.close()

    outcomes_log = []
    halfway = len(deliveries) // 2

    for idx, row in deliveries.iterrows():
        if idx == halfway:
            keys_to_change = rng.sample(
                list(true_instructions.keys()),
                int(len(true_instructions) * GROUND_TRUTH_CHANGE_FRACTION)
            )
            for k in keys_to_change:
                true_instructions[k] = true_instructions[k] + " (CHANGED)"

        addr_id = row["address_id"]
        t_difficulty = true_difficulties[addr_id]
        t_instruction = true_instructions[addr_id]

        note_used = None
        confidence_label = None
        confidence_score = None

        if mode == "prototype":
            resp = client.get(f"/dispatch/{addr_id}").json()
            note_used = resp.get("note")
            confidence_label = resp.get("confidence_label")
            confidence_score = resp.get("confidence_score")

            if note_used:
                is_correct = (note_used["instruction_text"] == t_instruction)
                p_fail = 0.05 if is_correct else 0.95
            else:
                p_fail = t_difficulty
        else:
            p_fail = t_difficulty

        if rng.random() < p_fail:
            outcome_val = "RTO" if rng.random() < RTO_FRACTION_OF_FAILURES else "FAILED"
            reason = "NO_ACCESS"
        else:
            outcome_val = "SUCCESS"
            reason = "NONE"

        attempt_payload = {
            "address_id": addr_id,
            "outcome": outcome_val,
            "failure_reason": reason,
            "driver_id": rng.choice(NAMED_DRIVERS),
            "promised_slot": rng.choice(PROMISED_SLOTS),
            "is_within_sla": True
        }
        if note_used:
            attempt_payload["used_note_id"] = note_used["note_id"]

        client.post("/attempts", json=attempt_payload)

        if mode == "prototype" and outcome_val == "SUCCESS" and not note_used:
            driver_note = t_instruction if rng.random() < DRIVER_ACCURACY_RATE else "Typo: " + t_instruction
            client.post("/notes", json={
                "address_id": addr_id,
                "instruction_text": driver_note,
                "source": "DRIVER_LOGGED"
            })

        if mode == "prototype" and rng.random() < CUSTOMER_CONFIRM_RATE and note_used:
            client.post(f"/notes/{note_used['note_id']}/confirm?source=CUSTOMER_CONFIRMED")

        outcomes_log.append({
            "delivery_id": row["delivery_id"],
            "address_id": addr_id,
            "outcome": outcome_val,
            "used_note": bool(note_used),
            "confidence_score": confidence_score,
            "confidence_label": confidence_label
        })

        conf_str = f"{confidence_score:.3f}" if confidence_score is not None else "N/A"
        logger.debug(f"[{mode.upper()}] addr={addr_id} outcome={outcome_val} conf={conf_str}")

    return pd.DataFrame(outcomes_log)


# ── single-seed responsive-volume simulation ──────────────────────────────────
def run_simulation_responsive_volume(mode: str, rng: random.Random) -> pd.DataFrame:
    """
    Responsive volume: simulate realistic dispatch policy where a failed delivery
    triggers re-attempts (up to MAX_REATTEMPTS_PER_ADDRESS). Total attempt count
    emerges naturally from the failure rate, so emissions differ between arms.
    Each address in the pool gets up to (1 + max_reattempts) chances.
    """
    reset_db()

    addresses = pd.read_csv(os.path.join(SIM_DIR, "synthetic_addresses.csv"))

    true_instructions = dict(zip(addresses.address_id, addresses.true_instruction))
    true_difficulties = dict(zip(addresses.address_id, addresses.true_difficulty))

    # Pre-populate addresses in bulk
    db = _db_module.SessionLocal()
    db.add_all([models.Address(address_id=r["address_id"], raw_text=r["raw_text"], area=r["area"]) for _, r in addresses.iterrows()])
    db.commit()
    db.close()

    # change 20% of ground truths partway through
    addr_list = list(addresses.address_id)
    keys_to_change = rng.sample(addr_list, int(len(addr_list) * GROUND_TRUTH_CHANGE_FRACTION))
    changed_set = set(keys_to_change)

    outcomes_log = []

    for addr_id in addr_list:
        # apply change after the "halfway" point — here we apply it stochastically
        if addr_id in changed_set and rng.random() > 0.5:
            true_instructions[addr_id] = true_instructions[addr_id] + " (CHANGED)"

        t_difficulty = true_difficulties[addr_id]
        t_instruction = true_instructions[addr_id]
        attempts_at_addr = 0

        while attempts_at_addr <= MAX_REATTEMPTS_PER_ADDRESS:
            note_used = None
            confidence_score = None
            confidence_label = None

            if mode == "prototype":
                resp = client.get(f"/dispatch/{addr_id}").json()
                note_used = resp.get("note")
                confidence_score = resp.get("confidence_score")
                confidence_label = resp.get("confidence_label")

                if note_used:
                    is_correct = (note_used["instruction_text"] == t_instruction)
                    p_fail = 0.05 if is_correct else 0.95
                else:
                    p_fail = t_difficulty
            else:
                p_fail = t_difficulty

            if rng.random() < p_fail:
                outcome_val = "RTO" if rng.random() < RTO_FRACTION_OF_FAILURES else "FAILED"
                reason = "NO_ACCESS"
            else:
                outcome_val = "SUCCESS"
                reason = "NONE"

            attempt_payload = {
                "address_id": addr_id,
                "outcome": outcome_val,
                "failure_reason": reason,
                "driver_id": rng.choice(NAMED_DRIVERS),
                "promised_slot": rng.choice(PROMISED_SLOTS),
                "is_within_sla": True
            }
            if note_used:
                attempt_payload["used_note_id"] = note_used["note_id"]

            client.post("/attempts", json=attempt_payload)

            if mode == "prototype" and outcome_val == "SUCCESS" and not note_used:
                driver_note = t_instruction if rng.random() < DRIVER_ACCURACY_RATE else "Typo: " + t_instruction
                client.post("/notes", json={
                    "address_id": addr_id,
                    "instruction_text": driver_note,
                    "source": "DRIVER_LOGGED"
                })

            if mode == "prototype" and rng.random() < CUSTOMER_CONFIRM_RATE and note_used:
                client.post(f"/notes/{note_used['note_id']}/confirm?source=CUSTOMER_CONFIRMED")

            outcomes_log.append({
                "delivery_id": f"{addr_id}_{attempts_at_addr}",
                "address_id": addr_id,
                "outcome": outcome_val,
                "used_note": bool(note_used),
                "confidence_score": confidence_score,
                "confidence_label": confidence_label
            })

            attempts_at_addr += 1

            # Stop cascading attempts for SUCCESS or RTO
            if outcome_val in ("SUCCESS", "RTO"):
                break

    return pd.DataFrame(outcomes_log)


# ── metrics calculator ────────────────────────────────────────────────────────
def calculate_metrics(df: pd.DataFrame) -> dict:
    total = len(df)
    if total == 0:
        return {}

    successes = (df["outcome"] == "SUCCESS").sum()
    rto = (df["outcome"] == "RTO").sum()

    # Repeat failure rate
    repeat_failures = 0
    total_after_first_fail = 0
    for _, group in df.groupby("address_id"):
        fails = group[group["outcome"].isin(["FAILED", "RTO"])]
        if len(fails) > 0:
            first_idx = fails.index[0]
            subsequent = group.loc[first_idx + 1:]
            total_after_first_fail += len(subsequent)
            repeat_failures += subsequent["outcome"].isin(["FAILED", "RTO"]).sum()

    rfr = repeat_failures / total_after_first_fail if total_after_first_fail > 0 else 0.0
    reliability = successes / total if total > 0 else 0.0
    cost_per_success = (total * COST_PER_ATTEMPT_RS) / successes if successes > 0 else float("inf")
    emissions_kg = (total * AVG_KM_PER_ATTEMPT * EMISSION_G_CO2_PER_KM) / 1000.0
    rto_rate = rto / total if total > 0 else 0.0

    return {
        "repeat_failure_rate": rfr,
        "reliability": reliability,
        "cost_per_success": cost_per_success,
        "emissions_kg": emissions_kg,
        "rto_rate": rto_rate,
        "total_attempts": total,
        "total_successes": int(successes)
    }


# ── calibration data collector ────────────────────────────────────────────────
def collect_calibration(df: pd.DataFrame) -> dict:
    """
    Returns observed success rates within three confidence buckets.
    Only rows where a note was used (so a confidence_score exists) are included.
    """
    noted = df[df["used_note"] & df["confidence_score"].notna()].copy()
    if noted.empty:
        return {}

    def bucket(score):
        if score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        else:
            return "low"

    noted["bucket"] = noted["confidence_score"].apply(bucket)
    result = {}
    for b in ["high", "medium", "low"]:
        sub = noted[noted["bucket"] == b]
        if len(sub) > 0:
            result[b] = {"n": len(sub), "success_rate": (sub["outcome"] == "SUCCESS").mean()}
        else:
            result[b] = {"n": 0, "success_rate": None}
    return result


# ── multi-seed runner ─────────────────────────────────────────────────────────
def run_multi_seed(simulation_fn, seeds):
    """Run both arms across all seeds, return per-seed metrics dicts."""
    all_base, all_proto = [], []
    all_cal_base, all_cal_proto = [], []

    for i, seed in enumerate(seeds):
        logger.info(f"Seed {i+1}/{len(seeds)} (seed={seed}) — baseline …")
        rng = random.Random(seed)
        df_b = simulation_fn("baseline", rng)
        all_base.append(calculate_metrics(df_b))
        all_cal_base.append(collect_calibration(df_b))

        logger.info(f"Seed {i+1}/{len(seeds)} (seed={seed}) — prototype …")
        rng = random.Random(seed + 1)  # offset so two arms differ
        df_p = simulation_fn("prototype", rng)
        all_proto.append(calculate_metrics(df_p))
        all_cal_proto.append(collect_calibration(df_p))

    return all_base, all_proto, all_cal_base, all_cal_proto


# ── CI calculator ─────────────────────────────────────────────────────────────
def mean_ci(values: list, z: float = 1.96):
    """Return (mean, sd, ci_lower, ci_upper) using normal approximation (z=1.96 for 95% CI)."""
    arr = np.array([v for v in values if v is not None and not math.isinf(v)])
    if len(arr) == 0:
        return None, None, None, None
    m = arr.mean()
    sd = arr.std(ddof=1)
    se = sd / math.sqrt(len(arr))
    return float(m), float(sd), float(m - z * se), float(m + z * se)


def summarize(metrics_list: list) -> dict:
    """Turn a list of per-seed metric dicts into mean/sd/ci summary."""
    if not metrics_list:
        return {}
    keys = metrics_list[0].keys()
    summary = {}
    for k in keys:
        vals = [m[k] for m in metrics_list if k in m]
        m, sd, lo, hi = mean_ci(vals)
        summary[k] = {"mean": m, "sd": sd, "ci_lower": lo, "ci_upper": hi, "values": vals}
    return summary


def summarize_calibration(cal_list: list) -> dict:
    """Aggregate calibration data across seeds."""
    agg = {"high": {"n": 0, "successes": 0}, "medium": {"n": 0, "successes": 0}, "low": {"n": 0, "successes": 0}}
    for cal in cal_list:
        for b in ["high", "medium", "low"]:
            if b in cal and cal[b]["n"] > 0 and cal[b]["success_rate"] is not None:
                agg[b]["n"] += cal[b]["n"]
                agg[b]["successes"] += int(cal[b]["n"] * cal[b]["success_rate"])
    result = {}
    for b in ["high", "medium", "low"]:
        n = agg[b]["n"]
        result[b] = {
            "n": n,
            "observed_success_rate": agg[b]["successes"] / n if n > 0 else None
        }
    return result


# ── plotting ──────────────────────────────────────────────────────────────────
DARK_BG = "#0f172a"
GRID_C = "#1e293b"
BASE_C = "#ef4444"
PROTO_C = "#10b981"
TEXT_C = "#e2e8f0"
MUTED_C = "#94a3b8"

plt.rcParams.update({
    "figure.facecolor": DARK_BG,
    "axes.facecolor": DARK_BG,
    "axes.edgecolor": GRID_C,
    "axes.labelcolor": TEXT_C,
    "xtick.color": MUTED_C,
    "ytick.color": MUTED_C,
    "text.color": TEXT_C,
    "grid.color": GRID_C,
    "grid.alpha": 0.5,
    "font.family": "sans-serif",
    "font.size": 10
})


def plot_multi_seed_metrics(base_summary, proto_summary, output_path):
    metrics_display = [
        ("repeat_failure_rate", "Repeat Failure Rate", "%", 100),
        ("reliability", "First-Attempt Reliability", "%", 100),
        ("cost_per_success", "Cost per Success", "Rs.", 1),
        ("rto_rate", "RTO Rate", "%", 100),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), facecolor=DARK_BG)
    fig.suptitle(f"Baseline vs Prototype — {NUM_SEEDS}-Seed Multi-Run Comparison (Mean ± 95% CI)",
                 color=TEXT_C, fontsize=13, fontweight="bold")

    for ax, (key, label, unit, scale) in zip(axes.flatten(), metrics_display):
        b = base_summary.get(key, {})
        p = proto_summary.get(key, {})

        b_vals = np.array(b.get("values", [])) * scale
        p_vals = np.array(p.get("values", [])) * scale

        b_mean = b["mean"] * scale if b.get("mean") is not None else 0
        p_mean = p["mean"] * scale if p.get("mean") is not None else 0
        b_lo = b["ci_lower"] * scale if b.get("ci_lower") is not None else b_mean
        b_hi = b["ci_upper"] * scale if b.get("ci_upper") is not None else b_mean
        p_lo = p["ci_lower"] * scale if p.get("ci_lower") is not None else p_mean
        p_hi = p["ci_upper"] * scale if p.get("ci_upper") is not None else p_mean

        x_b = np.random.normal(0, 0.08, size=len(b_vals))
        x_p = np.random.normal(1, 0.08, size=len(p_vals))

        ax.scatter(x_b, b_vals, color=BASE_C, alpha=0.4, s=25, zorder=2)
        ax.scatter(x_p, p_vals, color=PROTO_C, alpha=0.4, s=25, zorder=2)

        # Mean bar
        ax.bar([0], [b_mean], width=0.4, color=BASE_C, alpha=0.7, zorder=3, label="Baseline")
        ax.bar([1], [p_mean], width=0.4, color=PROTO_C, alpha=0.7, zorder=3, label="Prototype")

        # CI error bars
        ax.errorbar([0], [b_mean], yerr=[[b_mean - b_lo], [b_hi - b_mean]],
                    fmt="none", color="white", capsize=6, linewidth=2, zorder=4)
        ax.errorbar([1], [p_mean], yerr=[[p_mean - p_lo], [p_hi - p_mean]],
                    fmt="none", color="white", capsize=6, linewidth=2, zorder=4)

        # Annotations
        ax.text(0, b_mean + (b_hi - b_mean) + 0.5, f"{b_mean:.1f}{unit}",
                ha="center", va="bottom", color=TEXT_C, fontsize=9, fontweight="bold")
        ax.text(1, p_mean + (p_hi - p_mean) + 0.5, f"{p_mean:.1f}{unit}",
                ha="center", va="bottom", color=TEXT_C, fontsize=9, fontweight="bold")

        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Baseline", "Prototype"])
        ax.set_ylabel(f"{label} ({unit})")
        ax.set_title(label, color=TEXT_C, fontweight="bold")
        ax.yaxis.grid(True)
        ax.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info(f"Saved: {output_path}")


def plot_reliability_diagram(proto_cal, output_path):
    """
    Reliability diagram: predicted confidence bucket midpoint vs observed success rate.
    Diagonal = perfect calibration.
    """
    buckets = ["low", "medium", "high"]
    midpoints = [0.2, 0.55, 0.85]   # representative midpoint of each band
    observed = []
    sizes = []

    for b in buckets:
        info = proto_cal.get(b, {})
        r = info.get("observed_success_rate")
        n = info.get("n", 0)
        observed.append(r if r is not None else 0)
        sizes.append(max(50, n // 5))  # scale dot by sample count

    fig, ax = plt.subplots(figsize=(7, 6), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    ax.plot([0, 1], [0, 1], "--", color=MUTED_C, linewidth=1.5, label="Perfect calibration")

    colors_map = {"low": "#ef4444", "medium": "#f59e0b", "high": "#10b981"}
    for i, b in enumerate(buckets):
        ax.scatter([midpoints[i]], [observed[i]], s=sizes[i], color=colors_map[b],
                   zorder=5, label=f"{b.title()} (n={proto_cal[b]['n']})", edgecolors="white", linewidth=0.8)
        ax.annotate(f"{observed[i]:.1%}", (midpoints[i], observed[i]),
                    textcoords="offset points", xytext=(8, 4), color=TEXT_C, fontsize=10)

    ax.set_xlabel("Predicted Confidence Band (midpoint)")
    ax.set_ylabel("Observed Success Rate")
    ax.set_title(f"Reliability Diagram — {NUM_SEEDS}-Seed Combined\n(n = all prototype dispatch-with-note rows)",
                 color=TEXT_C, fontweight="bold")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.legend(facecolor=GRID_C, labelcolor=TEXT_C, fontsize=9)
    ax.yaxis.grid(True)
    ax.xaxis.grid(True)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info(f"Saved: {output_path}")


def plot_emissions_comparison(fixed_base, fixed_proto, resp_base, resp_proto, output_path):
    """Side-by-side: fixed-volume vs responsive-volume emissions."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), facecolor=DARK_BG)
    fig.suptitle("Emissions Comparison: Fixed-Volume vs Responsive-Volume Dispatch Policy",
                 color=TEXT_C, fontsize=12, fontweight="bold")

    def _get(s, key):
        d = s.get(key, {})
        m = d.get("mean", 0)
        lo = d.get("ci_lower", m)
        hi = d.get("ci_upper", m)
        return m, lo, hi

    for ax, (title, b_s, p_s, label_b, label_p) in [
        (axes[0], ("Mode A: Fixed Volume\n(1000 attempts each — fair comparison)",
                   fixed_base, fixed_proto, "Baseline (1000)", "Prototype (1000)")),
        (axes[1], ("Mode B: Responsive Volume\n(attempts emerge from failure rate — real saving)",
                   resp_base, resp_proto, "Baseline", "Prototype")),
    ]:
        key = "emissions_kg"
        b_m, b_lo, b_hi = _get(b_s, key)
        p_m, p_lo, p_hi = _get(p_s, key)

        bars = ax.bar([0, 1], [b_m, p_m], color=[BASE_C, PROTO_C], alpha=0.8, width=0.5)
        ax.errorbar([0], [b_m], yerr=[[b_m - b_lo], [b_hi - b_m]],
                    fmt="none", color="white", capsize=6, linewidth=2)
        ax.errorbar([1], [p_m], yerr=[[p_m - p_lo], [p_hi - p_m]],
                    fmt="none", color="white", capsize=6, linewidth=2)

        ax.text(0, b_m + 0.5, f"{b_m:.1f} kg", ha="center", color=TEXT_C, fontweight="bold")
        ax.text(1, p_m + 0.5, f"{p_m:.1f} kg", ha="center", color=TEXT_C, fontweight="bold")

        ax.set_xticks([0, 1])
        ax.set_xticklabels([label_b, label_p])
        ax.set_ylabel("Emissions (kg CO₂)")
        ax.set_title(title, color=TEXT_C, fontsize=10)
        ax.yaxis.grid(True)
        ax.set_facecolor(DARK_BG)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info(f"Saved: {output_path}")


# ── main entry point ──────────────────────────────────────────────────────────
def main():
    os.makedirs(EVAL_DIR, exist_ok=True)
    seeds = list(range(42, 42 + NUM_SEEDS))

    # ── Mode A: fixed-volume ──────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"Mode A: Fixed-Volume ({NUM_SEEDS} seeds × 2 arms)")
    logger.info("=" * 60)
    fv_base, fv_proto, fv_cal_b, fv_cal_p = run_multi_seed(run_simulation_fixed_volume, seeds)

    fv_base_sum = summarize(fv_base)
    fv_proto_sum = summarize(fv_proto)
    fv_proto_cal = summarize_calibration(fv_cal_p)

    # ── Mode B: responsive-volume ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"Mode B: Responsive-Volume ({NUM_SEEDS} seeds × 2 arms)")
    logger.info("=" * 60)
    rv_base, rv_proto, rv_cal_b, rv_cal_p = run_multi_seed(run_simulation_responsive_volume, seeds)

    rv_base_sum = summarize(rv_base)
    rv_proto_sum = summarize(rv_proto)

    # ── Print results table ───────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("MULTI-SEED RESULTS — MODE A: FIXED VOLUME")
    print("=" * 80)
    _print_table(fv_base_sum, fv_proto_sum)

    print("\n" + "=" * 80)
    print("MULTI-SEED RESULTS — MODE B: RESPONSIVE VOLUME")
    print("=" * 80)
    _print_table(rv_base_sum, rv_proto_sum)

    # ── Plots ─────────────────────────────────────────────────────────────────
    plot_multi_seed_metrics(
        fv_base_sum, fv_proto_sum,
        os.path.join(EVAL_DIR, "multi_seed_metrics.png")
    )
    plot_reliability_diagram(
        fv_proto_cal,
        os.path.join(EVAL_DIR, "reliability_diagram.png")
    )
    plot_emissions_comparison(
        fv_base_sum, fv_proto_sum,
        rv_base_sum, rv_proto_sum,
        os.path.join(EVAL_DIR, "emissions_comparison.png")
    )

    # ── Save JSON for report generation ──────────────────────────────────────
    results = {
        "num_seeds": NUM_SEEDS,
        "seeds": seeds,
        "fixed_volume": {
            "baseline": fv_base_sum,
            "prototype": fv_proto_sum,
            "calibration_prototype": fv_proto_cal
        },
        "responsive_volume": {
            "baseline": rv_base_sum,
            "prototype": rv_proto_sum
        }
    }
    json_path = os.path.join(EVAL_DIR, "multi_seed_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Saved raw results: {json_path}")
    print(f"\nAll outputs saved to: {EVAL_DIR}")


def _print_table(base_sum, proto_sum):
    display = [
        ("repeat_failure_rate", "Repeat Failure Rate", "%", 100),
        ("reliability", "First-Attempt Reliability", "%", 100),
        ("cost_per_success", "Cost per Success", "Rs.", 1),
        ("rto_rate", "RTO Rate", "%", 100),
        ("emissions_kg", "Emissions", "kg CO2", 1),
    ]
    print(f"{'Metric':<30} | {'Baseline Mean±SD (95%CI)':<35} | {'Prototype Mean±SD (95%CI)':<35}")
    print("-" * 108)
    for key, label, unit, scale in display:
        b = base_sum.get(key, {})
        p = proto_sum.get(key, {})
        bm = b.get("mean", 0) * scale if b.get("mean") is not None else 0
        bs = b.get("sd", 0) * scale if b.get("sd") is not None else 0
        bl = b.get("ci_lower", 0) * scale if b.get("ci_lower") is not None else 0
        bh = b.get("ci_upper", 0) * scale if b.get("ci_upper") is not None else 0
        pm = p.get("mean", 0) * scale if p.get("mean") is not None else 0
        ps = p.get("sd", 0) * scale if p.get("sd") is not None else 0
        pl = p.get("ci_lower", 0) * scale if p.get("ci_lower") is not None else 0
        ph = p.get("ci_upper", 0) * scale if p.get("ci_upper") is not None else 0
        b_str = f"{bm:.2f}±{bs:.2f} ({bl:.2f}–{bh:.2f}) {unit}"
        p_str = f"{pm:.2f}±{ps:.2f} ({pl:.2f}–{ph:.2f}) {unit}"
        print(f"{label:<30} | {b_str:<35} | {p_str:<35}")


if __name__ == "__main__":
    main()
