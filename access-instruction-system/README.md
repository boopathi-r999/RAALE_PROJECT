# Access-Instruction Capture & Reuse System — Final (Review 2 · AI Immersion Edition)

[![Tests](https://img.shields.io/badge/tests-11%2F11%20passing-brightgreen)]()
[![ML Model](https://img.shields.io/badge/model-Random%20Forest%20(AUC%200.76)-blue)]()
[![Simulation](https://img.shields.io/badge/simulation-multi--seed-purple)]()

> **Demo video:** `demo/demo_video.mp4` · **Viva prep:** [`docs/viva_prep.md`](docs/viva_prep.md) · **Model Card:** [`ml/model_card.md`](ml/model_card.md) · **Dataset card:** [`docs/dataset_card.md`](docs/dataset_card.md)

## What Changed Since Review 1

| Section | What Was Done | Files |
|---|---|---|
| **§1 Machine Learning** | Supervised Delivery Success Predictor (Random Forest vs Logistic Regression, 80/20 holdout, ROC-AUC 0.76) | `ml/train_model.py`, `ml/model_card.md`, `ml/artifacts/` |
| **§2 Realistic Dataset** | 400 Indian addresses (Chennai, Bangalore, Coimbatore, Trichy, Hyderabad), 20 named drivers, SLA slots | `simulation/generate_data.py`, `docs/dataset_card.md` |
| **§3 Statistical Rigour** | Multi-seed simulation experiment, mean±SD, 95% CI, error-bar charts | `simulation/experiment.py`, `evaluation/multi_seed_metrics.png` |
| **§4 Emissions Model** | Added responsive-volume mode; emissions now differ between arms | `simulation/experiment.py`, `simulation/config.py`, `evaluation/emissions_comparison.png` |
| **§5 Customer Notification** | Real `POST /notify` endpoint, `NOTIFY_MODE` flag, channel plan | `backend/main.py`, `docs/notification_channel_plan.md` |
| **§6 Dedup Workflow** | Similarity flagging, ops merge/keep-separate decision, Edge Case #6 | `backend/main.py`, `backend/models.py`, `tests/test_edge_cases.py` |
| **§7 System Hardening** | Input validation, rate guard, no false precision guarantee on risk endpoint | `backend/main.py`, `backend/schemas.py`, `tests/test_edge_cases.py` |
| **§8 Evaluation Report** | Full rewrite: multi-seed table, two emissions modes, reliability diagram | `evaluation/evaluation_report.md` |
| **§9 Ops Dashboard** | Driver leaderboard, area-level breakdown, interactive ML risk forecast panel | `frontend/`, `backend/main.py` |
| **§10 Viva Prep** | 11 Q&A pairs covering rule-based confidence vs ML models and strict uncertainty | `docs/viva_prep.md` |

---

## Machine Learning Component (Delivery Success Predictor)

Alongside the driver-facing rule-based confidence engine (Laplace smoothing + exponential time decay), the system integrates a genuinely trained supervised classification pipeline (`ml/train_model.py`):

- **Target:** Binary attempt outcome (`1` for Success, `0` for Failed/RTO).
- **Features (Strict Anti-Leakage):** Area archetype, day-of-week, promised SLA time slot, access note presence, note confidence band, days since last address success, address cumulative prior failure rate, and driver historical success rate.
- **Architectures Evaluated:**
  - **Baseline:** Logistic Regression ($C=1.0$, L2 penalty) — Accuracy 75.83%, Precision 79.41%, ROC-AUC 0.7372.
  - **Selected:** Random Forest (100 estimators, max depth 6) — **Accuracy 78.00%, Precision 81.00%, ROC-AUC 0.7589**.
- **Strict Separation Principle:** The ML risk score is exposed via `GET /dispatch/{address_id}/risk-score` solely for Ops dispatch planning. It is **never** shown in the Driver Dispatch View to prevent confusing drivers with conflicting signals or false precision.
- **No False Precision:** All ML risk probabilities are rounded to the nearest 5% (e.g. `~35% estimated failure risk`), guaranteed by automated tests.

---

## Key Features

1. **Driver Dispatch View** — Authentic Indian addresses prominently displayed, named driver selector (20 fleet drivers), confidence-scored access notes, cold-start explicit state, and inline note capture.
2. **Customer Confirmation Portal** — Confirm/correct flow, +3 weight boost for customer confirmations, rate-limited confirmation endpoint.
3. **Address Notes Explorer + Merge Review** — Human-readable address table, duplicate flagging (SequenceMatcher similarity ≥0.70), side-by-side ops comparison, explicit Merge/Keep-Separate decision with audit log.
4. **Ops Dashboard & Model Insights** — Multi-seed mean±CI results, emissions mode toggle, area-level failure breakdown, driver leaderboard, ML model comparison table, feature importance charts, and interactive risk evaluator.
5. **Edge Case Demo (×6)** — 6 interactive live scenarios including human-in-the-loop duplicate review and contradiction decay.

---

## Summary Metrics (20-Seed Multi-Run, Mode A Fixed Volume)

| Metric | Baseline | Target | Prototype Mean | 95% CI | Status |
|---|---|---|---|---|---|
| **Repeat Failure Rate** | ~51% | <40% | **~37%** | see report | ✅ Exceeded |
| **First-Attempt Reliability** | ~57% | >70% | **~71%** | see report | ✅ Met |
| **Cost per Success** | ~Rs.71 | <Rs.60 | **~Rs.56** | see report | ✅ Exceeded |
| **RTO Rate** | ~7.7% | <6% | **~6.5%** | see report | ⚠ Near-miss |

> Exact numbers with CI bounds: see [`evaluation/evaluation_report.md`](evaluation/evaluation_report.md) and [`evaluation/multi_seed_metrics.png`](evaluation/multi_seed_metrics.png).

---

## How to Run

```powershell
# Navigate to project directory
cd d:\boopathiproj\access-instruction-system

# Seed database with synthetic data
python simulation/seed_db.py

# Start FastAPI backend (default: simulated notification mode)
uvicorn backend.main:app --reload

# To run with real notification mode:
$env:NOTIFY_MODE="real"; uvicorn backend.main:app --reload

# Open in browser
# http://127.0.0.1:8000
```

---

## Running Tests & Simulation

```powershell
# Run all 10 edge case tests
python -m pytest tests/test_edge_cases.py -v

# Run the 20-seed simulation experiment (takes ~5-10 minutes)
# Outputs: evaluation/multi_seed_metrics.png, reliability_diagram.png, emissions_comparison.png
python simulation/experiment.py

# Regenerate synthetic data (if needed)
python simulation/generate_data.py

# Swap in real company data (see docs/dataset_card.md for schema)
python simulation/real_data_adapter.py --addresses path/to/real.csv --deliveries path/to/deliveries.csv
```

---

## Config Flags

| Variable | Values | Default | Effect |
|---|---|---|---|
| `NOTIFY_MODE` | `simulated`, `real` | `simulated` | Controls whether `POST /notify` calls a real SMS API or logs locally |
| `NUM_SEEDS` (in `config.py`) | integer | `20` | Number of seeds for multi-run experiment |
| `HALF_LIFE_DAYS` (in `uncertainty.py`) | float | `30.0` | Time-decay half-life for confidence scores |

---

## File Structure

```
/access-instruction-system
  /backend
    main.py              FastAPI app (validation, rate guard, logging, all endpoints)
    models.py            SQLAlchemy models (+ DuplicateMergeLog, NotifyLog)
    schemas.py           Pydantic schemas (+ input validators)
    uncertainty.py       Laplace + time-decay confidence model
    database.py          SQLite engine setup
  /simulation
    experiment.py        Multi-seed experiment runner (Mode A + B)
    generate_data.py     Synthetic data generator (cited assumptions)
    config.py            ★ All constants (costs, emissions, seeds) — single source of truth
    real_data_adapter.py Adapter script for swapping in real CSV data
    seed_db.py           DB seeding script
    synthetic_addresses.csv
    synthetic_deliveries.csv
  /frontend
    index.html           5-tab UI + duplicate review panel + notification UI
    app.js               All UI logic including merge workflow, emissions toggle
    style.css            Dark glassmorphism design + new UI component styles
  /evaluation
    evaluation_report.md ★ Full rewrite: multi-seed table, two emissions modes, calibration
    multi_seed_metrics.png  Error-bar charts (20-seed)
    reliability_diagram.png Confidence calibration across all seeds
    emissions_comparison.png Fixed vs responsive volume emissions
    multi_seed_results.json Raw data (served at /evaluation/multi_seed_results.json)
  /docs
    dataset_card.md      Generation method, assumptions, limitations, real-data guide
    notification_channel_plan.md  SMS/email/WhatsApp options + compliance requirements
    stakeholder_feedback.md  4-heuristic structured self-evaluation
    viva_prep.md         8 crisp Q&A pairs for viva defence
    problem_analysis.md
    workflow_map.md
  /demo
    demo_video.mp4       Screen recording (record using demo_script.md)
  /tests
    test_edge_cases.py   10 tests (6 edge cases + 4 system hardening tests)
  demo_script.md         Updated recording guide for all new features
  README.md              This file
```
