# Stakeholder Validation — Heuristic Evaluation

**Document:** Structured Heuristic Self-Evaluation  
**System:** Access-Instruction Capture & Reuse System  
**Evaluator:** Boopathi (project author, structured self-evaluation)  
**Date:** October 2026

> **Honest disclosure:** This is a structured heuristic self-evaluation, not a real external stakeholder study. No external drivers, ops managers, or customers were interviewed for this document. This evaluation follows established usability heuristics and ops workflow principles as a substitute. It should be treated as a reasoned design audit, not empirical user validation. A real pilot study with 3–5 frontline drivers would substantially change confidence in the findings below.

---

## Evaluation Framework

Four heuristics were selected as most directly relevant to a last-mile ops tool:

1. **Uncertainty transparency** — Does the system ever hide uncertainty or present unconfirmed data as verified fact?
2. **Ops actionability** — Can an ops manager act on a confidence signal within 2 clicks?
3. **Failure recovery** — Does a failure path leave the user stuck without guidance?
4. **Trust anchoring** — Does the system make it clear *why* it is confident or uncertain, not just that it is?

---

## Heuristic 1: Uncertainty Transparency

**Question:** Does the system ever hide uncertainty or present unconfirmed data as verified fact?

**Evidence:**

- Every dispatch response includes an explicit confidence band ("High / Medium / Low") derived from a computed score, never a hard-coded label. Cold-start state is explicitly labelled: *"No verified access note — attempt as a standard delivery."* This prevents the blank-field ambiguity where an absent note could be misread as "confirmed clear access."
- Notes sourced from `DRIVER_LOGGED` carry a visible source tag at dispatch, distinguishing them from `CUSTOMER_CONFIRMED` notes.
- Confidence scores decay over time (30-day half-life). A note that was High confidence 45 days ago is shown as Medium without manual intervention.
- The calibration diagram (see `evaluation/reliability_diagram.png`) shows actual success rates of ~88% for High, ~54% for Medium, ~36% for Low — consistent with the labels' implicit meaning.

**Score: 4/5.** Minor gap: the confidence score (e.g. `0.73`) is shown to ops managers but not to drivers (by design — drivers see the band label only). This is the correct trade-off, but a driver who asks "why is this Medium if I've delivered here 10 times successfully?" has no way to understand the time-decay component without asking ops. A future tooltip explaining "last confirmed 25 days ago" would close this gap.

---

## Heuristic 2: Ops Actionability

**Question:** Can an ops manager act on a confidence signal within 2 clicks?

**Evidence:**

- **Address Notes Explorer** → sorted by Lowest Confidence First → click "Audit Trail" (1 click) → see full note history and delivery outcomes for that address. This is 2 clicks from landing on the tab.
- The explorer now also flags potential duplicates inline (orange "⚠ Possible duplicate of ADDR_XXX" badge) — reducing the cognitive cost of finding merge candidates.
- The duplicate merge workflow requires only: (1) review the side-by-side comparison, (2) click Merge or Keep Separate. Decision is logged with timestamp and manager ID.
- The Ops Dashboard shows multi-seed mean ± CI metrics and a reliability diagram — all visible on a single tab without scrolling on a 1080p display.

**Score: 4/5.** The merge review UI (currently shown as a raw JSON result in the Edge Case Demo tab) would benefit from a purpose-built comparison panel with the two addresses' note histories side by side. This is a frontend polish item, not a logic gap. The backend `/duplicates/{log_id}/decide` endpoint is production-ready.

---

## Heuristic 3: Failure Recovery

**Question:** Does a failure path leave the user stuck without guidance?

**Evidence tested:**

| Scenario | System response | Recovery path |
|---|---|---|
| Driver logs failure with a note in use | Banner: "Noted — instruction may be outdated, confidence will be adjusted." | Confidence drops; driver prompted to re-dispatch tomorrow with updated state |
| Driver dispatches to unknown address ID | Response: cold-start state, not an error screen | Driver knows to proceed without notes |
| Ops submits empty note text | Validation error: 422 with message "instruction_text too short" | Clear error message, form stays open |
| Same confirmation submitted >3× | 429 rate limit response with explanation | Prevents gaming; legitimate use case (single confirm) still works |
| Customer clicks confirmation link for address with no note | Portal shows "No existing note — please suggest instructions below" | Customer correction path opens |

**Score: 5/5.** Every tested failure path returns an actionable message, not a bare error code. No dead ends observed in testing.

---

## Heuristic 4: Trust Anchoring

**Question:** Does the system make it clear *why* it is confident, not just that it is?

**Evidence:**

- Dispatch response includes: confidence score, confidence label, last confirmed timestamp (shown as "confirmed 4 days ago"), and source (DRIVER_LOGGED vs CUSTOMER_CONFIRMED).
- Ops Dashboard calibration panel links confidence bands to empirical success rates — showing managers that "High confidence" means 88% actual success, not just "we think it's good."
- Audit trail shows every note with its confirmation and contradiction counts, creation timestamp, and source — enabling managers to reconstruct *why* a score changed over time.
- Structured logging (backend logs) records every dispatch, outcome, and confidence change with note_id, counts, and timestamps — a tracer for debugging wrong scores in production.

**Score: 4/5.** The audit trail does not yet show the *computed score at the time of each delivery*, only the current score. This makes it hard to reconstruct the exact score that a driver saw at dispatch time for a past delivery. A future improvement would snapshot the confidence score when logging each attempt.

---

## Summary Table

| Heuristic | Score | Highest Strength | Remaining Gap |
|---|---|---|---|
| Uncertainty Transparency | 4/5 | Cold-start explicit state, band labels, source tags | Driver cannot see time-decay explanation |
| Ops Actionability | 4/5 | 2-click audit trail, inline duplicate flags | Merge review needs side-by-side UI panel |
| Failure Recovery | 5/5 | All failure paths return actionable guidance | No gaps found in testing |
| Trust Anchoring | 4/5 | Calibration diagram, audit trail, structured logs | Confidence-at-dispatch not snapshot per attempt |

**Overall:** The system performs well on its core trust and transparency requirements. The two gaps identified (driver explanation of decay, snapshot confidence per attempt) are prioritised future enhancements, not blockers to a pilot deployment.

---

## What Real Stakeholder Feedback Would Add

If 3–5 drivers/ops managers were interviewed (which was not possible for this submission), the most likely findings based on comparable last-mile tech UX studies (e.g. Rivigo's driver app UX research, 2020) would be:

1. **Drivers prefer voice or icon-based confidence signals** over text bands — "a red/green dot is faster to interpret than 'Medium confidence' when you're at a gate."
2. **Ops managers want export-to-Excel**, not just a web dashboard — common feedback in any ops-tool pilot.
3. **Customers are suspicious of SMS from unknown numbers** — opt-in framing ("Your Shiprocket delivery has access instructions on file — confirm at link") performs better than generic "access instruction" branding.

These would be the first three items in a real pilot feedback integration.
