# Model Card — Delivery Success & Failure Risk Predictor

## Model Details
- **Model Name:** Delivery Success Predictor (`delivery_risk_model.joblib`)
- **Version:** 1.0 (Review 2 — AI Immersion Edition)
- **Architecture:** Supervised classification pipeline with categorical `OneHotEncoder` and `RandomForestClassifier` (100 estimators, max depth 6). Baseline comparison: `LogisticRegression` (L2 regularization, $C=1.0$).
- **Intended Task:** Operational risk estimation to forecast probability of delivery failure prior to dispatch for last-mile delivery operations.
- **License / Usage:** Educational demonstration for AI Immersion coursework.

---

## Intended Use & Strict Boundary
- **Primary Operational Audience:** Dispatch planners and Operations Managers (Ops Dashboard).
- **Out of Scope / Prohibited Use:** **Never surfaced in Driver Dispatch View.** Driver-facing guidance relies strictly on rule-based Laplace-smoothed note confidence to prevent confusing drivers with competing signals or false precision.
- **Output Presentation:** All risk estimates are rounded to the nearest 5% (e.g. `~35% estimated failure risk`) and always accompanied by the explanatory disclaimer.

---

## Training Data & Methodology
- **Dataset:** 3,000 sequential deliveries across 400 realistic Indian addresses (Chennai, Bangalore, Coimbatore, Trichy, Hyderabad) covering 180 continuous days.
- **Anti-Leakage Guarantee:** Every training row computes feature values strictly using attempts and notes *prior* to timestamp $t$. No future outcomes or post-hoc confirmations leak into the training matrix.
- **Split:** 80% Train (2,400 attempts), 20% Test (600 attempts), stratified on binary target `success`.

### Input Features

| Feature Name | Type | Description |
|---|---|---|
| `area` | Categorical | Area archetype (`apartment`, `gated community`, `industrial`, `standalone house`) |
| `slot` | Categorical | Promised delivery window (`10:00-13:00`, `14:00-17:00`, `17:00-20:00`) |
| `conf_band` | Categorical | Confidence band of access note at dispatch (`None`, `Low`, `Medium`, `High`) |
| `day_of_week` | Numerical (0–6) | Day of the week (Monday=0, Sunday=6) |
| `has_note` | Binary (0/1) | Whether a verified or driver-logged note exists at dispatch time |
| `days_since_last_success` | Numerical | Elapsed days since the last successful delivery to this address |
| `addr_hist_fail_rate` | Numerical [0, 1] | Historical failure fraction at this address prior to current attempt |
| `driver_hist_success_rate`| Numerical [0, 1] | Historical success rate of the assigned driver prior to current attempt |

---

## Quantitative Evaluation (80/20 Holdout Test Set)

| Metric | Logistic Regression (Baseline) | Random Forest (Selected) | Delta |
|---|---|---|---|
| **Accuracy** | 75.83% | **78.00%** | +2.17% |
| **Precision** | 79.41% | **81.00%** | +1.59% |
| **Recall** | 90.72% | **91.63%** | +0.91% |
| **F1 Score** | 0.8469 | **0.8599** | +0.0130 |
| **ROC-AUC** | 0.7372 | **0.7589** | +0.0217 |

### Why Random Forest Was Selected
Random Forest achieved higher ROC-AUC (0.76 vs 0.74) and F1 score (0.86 vs 0.85). Inspection of decision paths shows it captures the non-linear interaction between `area` (e.g. gated communities having steep penalty curves) and `addr_hist_fail_rate`, whereas Logistic Regression assumes monotonic log-odds across heterogeneous area archetypes.

---

## Visual Artifacts
- **Feature Importance:** `ml/artifacts/feature_importance.png` (Top predictors: `addr_hist_fail_rate`, `has_note`, `days_since_last_success`, `area_gated community`).
- **ROC & Confusion Matrix:** `ml/artifacts/model_evaluation.png` (Demonstrates clean separation and discriminative power on holdout test cases).

---

## Limitations & Honesty Statement
1. **Synthetic Training Foundation:** While the data generator incorporates realistic Indian geography, authentic address patterns, and published industry failure baselines (Delhivery / KPMG / Shadowfax), the model was trained on synthetic data. It is a demonstration of machine learning engineering, not a commercially deployed production risk model.
2. **Dynamic Concept Drift:** In real operations, sudden gate code rotations or road closures introduce abrupt non-stationarity. The model relies on `addr_hist_fail_rate` and `conf_band` as proxy indicators, but cannot anticipate zero-day environmental changes.
3. **Revalidation Roadmap:** To deploy in live logistics operations, the pipeline must be retrained on 90+ days of real fleet GPS and telematics logs via `simulation/real_data_adapter.py`.
