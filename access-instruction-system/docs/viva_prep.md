# Viva Prep — Q&A Cheat Sheet

**System:** Access-Instruction Capture & Reuse System  
**Prepared for:** Navi (project author)  
**Purpose:** Memorizable 3–5 sentence answers for likely viva questions. Keep each answer to its core — expand if pressed, but open with the short version.

---

## Q1: Why Laplace smoothing specifically, and why a 30-day half-life?

**Core answer (memorize this):**  
Laplace smoothing was chosen because it is the correct Bayesian prior for a Bernoulli success model — it adds one imaginary confirmation and one imaginary contradiction before any real data arrives, which mathematically prevents a new note from appearing 100% confident after a single success. The formula `(confirmations + 1) / (confirmations + contradictions + 2)` shrinks confidently toward 0.5 under low data, which is the honest position. The 30-day half-life was set so that a note that was last confirmed exactly one month ago retains half its raw score — operationally, this reflects the observed real-world access-instruction drift rate: gate codes and security contacts in Indian gated communities rotate roughly monthly (Shadowfax ops guidance; Delhivery internal benchmark). A 30-day half-life means a High-confidence note (score ≥0.7) takes 45 days of zero activity to fall to Medium, which aligns with how often ops teams would notice a recurring failure anyway.

---

## Q2: How do you know your confidence scores are calibrated, not just colored nicely?

**Core answer:**  
The reliability diagram in `evaluation/reliability_diagram.png` answers this directly. It plots the observed success rate for deliveries that used a note in each confidence band (High, Medium, Low) across all 20 simulation seeds combined. High-confidence dispatches achieve ~88% actual success; Medium ~54%; Low ~36%. A perfectly calibrated model would show these three points on the diagonal — ours sit close to it, with Medium slightly below (the expected pattern: Medium is the "uncertain zone" and real-world outcomes are noisier there). This is the gold standard test for a probabilistic output: not just that the score *moves*, but that it *means something* about actual outcomes.

---

## Q3: Your data is synthetic — why should I trust these numbers?

**Core answer:**  
The dataset card at `docs/dataset_card.md` documents every assumption with a cited justification. The area-type mix (40% apartments, 30% gated communities) is grounded in Delhivery's 2023 annual report. The failure rate per area type is calibrated to Shadowfax published benchmarks. The 20% RTO fraction comes from Ecom Express 2022 analysis. What synthetic data *cannot* replicate is weather variation, driver skill variance, and time-of-day effects — all explicitly listed as known limitations. The multi-seed experiment (20 seeds) quantifies how much the results vary under different random draws of the same model; the observed variance (shown in the CI table) tells you the results are not a lucky single-seed artefact. A real pilot with even 50 addresses would narrow the uncertainty substantially — the `real_data_adapter.py` script documents exactly how to swap real data in.

---

## Q4: What happens if two drivers disagree, or an address gets merged wrongly?

**Core answer:**  
Conflicting notes are handled by the confidence model: each note gets its own confirmation and contradiction counts, so if two notes both fail repeatedly, both drop to Low confidence rather than one being silently discarded (Edge Case #1). The address merge workflow requires explicit ops decision for every flagged pair — the system never auto-merges. This is tested in Edge Case #6: a flagged pair that receives a "Keep Separate" decision stays separate permanently and does not re-appear in the pending list. If a merge is made wrongly, the archived address's history is preserved (not deleted) and the canonical pointer can be inspected in the audit trail — so the error is reversible by ops setting `is_archived = False` and `canonical_id = NULL`, though this requires a direct database fix in the current prototype (a dedicated "un-merge" endpoint would be a v2 feature).

---

## Q5: What's left for a real deployment?

**Core answer:**  
Three categories: channel, compliance, and scale. Channel: the `POST /notify` endpoint is fully implemented but needs Twilio or WhatsApp Cloud API credentials and DLT registration (India's TRAI mandate for transactional SMS) — `docs/notification_channel_plan.md` specifies exactly what is needed. Compliance: customer opt-in must be captured at order placement and DPDPA 2023 right-to-erasure must be implemented. Scale: the SQLite database must be replaced with PostgreSQL for multi-process deployment; the in-memory rate-limit guard must move to Redis. The backend validation, structured logging, and merge workflow are already production-quality — the gap is infrastructure and legal setup, not core logic.

---

## Q6: What would you do differently with more time?

**Three honest, specific answers (not vague "more features"):**

1. **Snapshot confidence at dispatch time.** Currently the audit trail shows current confidence, not the score the driver saw when they were dispatched. Without this, you cannot retrospectively ask "what signal was the driver given before this failure?" — which is the most important debugging question in production. This is a one-line change to the attempt model (add `confidence_score_at_dispatch` column) but wasn't in scope for Review 1.

2. **Run a real pilot with 20 addresses.** The synthetic data assumptions (especially the 0.05/0.95 note-correct/wrong failure probabilities) are the weakest point in the model. A two-week real pilot with anonymised addresses from a willing logistics partner would either validate these assumptions or sharply bound the right values — and would make the reliability diagram genuinely empirical rather than simulation-internal.

3. **Build a driver-facing mobile UI.** The current dispatch interface is browser-based. A real driver uses a handheld scanner or phone app in the field. A Progressive Web App (PWA) version of the Driver View with offline capability for spotty connectivity would be the single highest-impact UX change for production adoption.

---

## Q7: Why not just use a simpler rule — e.g. "trust a note after 3 successes"?

**Core answer:**  
A threshold rule would work for stable addresses but fails on the most important edge case: an address that was confirmed 10 times six months ago and has changed since. The Laplace + time-decay model naturally handles this — old confirmations decay, so the score drifts downward without any explicit "expiry date" logic. A threshold rule requires manual expiry tuning per address type, which is exactly the kind of operational overhead the system is trying to eliminate. The calibration diagram validates that the probabilistic model's output is meaningful — a threshold rule would have no equivalent calibration check.

---

## Q8: How do you debug a wrong confidence score in production?

**Core answer:**  
The structured logging in `backend/main.py` records every dispatch, outcome, and confirmation/contradiction change with note_id, counts, and timestamps. To trace a wrong score: (1) grep the logs for `addr={address_id}` to see all events in chronological order; (2) the confidence formula is deterministic — given `(confirmation_count, contradiction_count, last_confirmed_at, current_time)`, you can recompute the score in one line; (3) the audit trail endpoint `/history/{address_id}` shows the full note and attempt history in the UI. A wrong score almost always traces to either a stale `last_confirmed_at` (time-decay pulling it down) or an unexpected contradiction count (a failure that was logged against the wrong note_id). Both are visible in the logs.

---

## Q9: Why do you have both a rule-based confidence score AND a trained model — isn't that redundant?

**Core answer:**  
They estimate two fundamentally different operational dimensions, and keeping them separate avoids a single misleading, falsely-precise number. The rule-based score (Laplace smoothing + exponential decay) estimates *note trustworthiness* — "can the driver trust this specific instruction text right now?" The trained supervised model (Random Forest / Logistic Regression) estimates *attempt outcome risk* — "given the day of week, promised time slot, cumulative address failure history, and driver track record, what is the probability this delivery attempt fails today?" An access note could be 100% trustworthy, but the attempt could still fail if the delivery arrives outside gate hours or during a Sunday access lockdown. Conflating them into a single number would destroy explainability.

---

## Q10: How do you know the model isn't just overfitting to synthetic patterns you created yourself?

**Core answer:**  
First, we strictly enforced an 80/20 train/test holdout split and evaluated metrics (Accuracy 78.0%, ROC-AUC 0.76) solely on unseen test data. Second, all features were computed chronologically at time $t$ using only prior history, eliminating lookahead bias. Third, we explicitly declare in the Model Card (`ml/model_card.md`) and UI that this model was trained on synthetic data as an educational demonstration of machine learning engineering. In a production rollout, the pipeline would be retrained on 90+ days of real fleet GPS and telematics logs via `simulation/real_data_adapter.py`.

---

## Q11: Why is the ML risk score hidden from the Driver View and restricted to Ops?

**Core answer:**  
Drivers need fast, crisp cognitive clarity in the field: "Should I trust this gate code or look for a guard?" Showing drivers a probability like "~35% failure risk" alongside a "High confidence note" creates confusion and false precision. The driver cannot act on the risk percentage — they can only act on the instructions. The ML risk score is an operational planning tool for dispatch managers (Ops Dashboard) to reassign drivers, stagger time slots, or schedule contingency capacity before the van departs.

