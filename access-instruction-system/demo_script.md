# Demo Script — Access-Instruction Capture & Reuse System
## Screen Recording Guide (Target: ≤3:30 total)

**Recording tool:** OBS Studio, Windows Game Bar (Win+G), or browser extension  
**Target output:** `/demo/demo_video.mp4`  
**Resolution:** 1920×1080 recommended  
**App URL:** http://127.0.0.1:8000

---

## Pre-recording Checklist

- [ ] Run `python simulation/seed_db.py` to ensure fresh seeded data
- [ ] Start server: `uvicorn backend.main:app --reload`
- [ ] Open http://127.0.0.1:8000 in a clean browser window (fullscreen, no bookmarks bar)
- [ ] Open DevTools → Console to show clean state (no errors)
- [ ] Have a real Address ID ready from the database (e.g. `ADDR_7F3A62C8`)
- [ ] Close Slack / email notifications

---

## Segment 1 — Problem Statement (20 seconds)

> **Narration:**  
> "Every day, millions of last-mile deliveries in India fail not because the package is wrong — but because the driver doesn't know how to get in. Gate codes, intercom numbers, security guard names — this information exists in drivers' heads but isn't captured. The next driver starts from zero. We call this the *cold start* problem, and it costs roughly Rs. 30 on every failed attempt."

*Show:* Ops Dashboard tab — point to the "Repeat Failure Rate: Baseline 51.3%" metric strip. Keep it brief — the number does the talking.

---

## Segment 2 — Driver View: Cold Start → Note Capture → Re-dispatch (50 seconds)

**Step 1 — Cold Start:**
1. Navigate to **Driver View** tab
2. Type an address ID that has no notes yet (e.g. `ADDR_COLD_DEMO`)
3. Click **Get Instructions**
4. Show the cold-start state: *"No verified access note — proceed as a standard delivery"* — low confidence badge

> **Narration:** "Without notes, the driver gets a cold-start warning. The system never pretends there's useful data when there isn't."

**Step 2 — Log Success + Note Capture:**
5. Click **Log Success** — show the inline note form appearing
6. Type: `Gate code 7821, call Ramesh at security before entering`
7. Click **Save Note** — show the success banner

> **Narration:** "After a successful delivery, the driver logs the access instruction. It's captured once — reused by every driver who follows."

**Step 3 — Re-dispatch with Note:**
8. Click **Get Instructions** again for the same address
9. Show the note appearing with a confidence badge (e.g. Medium 50%) and source tag `DRIVER_LOGGED`
10. Point to: "*confirmed today*" timestamp badge

> **Narration:** "Next time a driver hits this address, they get the instruction immediately — with a confidence band telling them how reliable it is."

---

## Segment 3 — Customer Confirmation Portal (30 seconds)

1. Navigate to **Customer Portal** tab
2. Enter the same address ID → click **Load Address Details**
3. Show: instruction on file, `Driver-logged` tag, "3× initial weight" label
4. Click **Confirm Details Are Correct**
5. Show: "Thank you! Verified (weight boosted by +3)" banner

> **Narration:** "The customer receives an SMS link and confirms the instruction. Customer confirmation carries 3× the weight of a driver log — because the customer lives there and knows best."

6. Go back to Driver View — re-dispatch the same address — show confidence has increased and source tag is now `CUSTOMER_CONFIRMED`

---

## Segment 4 — Address Notes Explorer: Lowest Confidence + Duplicate Review (30 seconds)

1. Navigate to **Address Explorer** tab
2. Default view: sorted by **Lowest Confidence First**
3. Point to the orange "⚠ Possible duplicate" badge on a flagged address pair
4. Click **Audit Trail** on the lowest-confidence address
5. Show the note history (contradictions, source, dates) and delivery attempt history
6. Click **Close** — return to table

> **Narration:** "Ops managers see which addresses need attention first — sorted by confidence, with duplicate flags surfaced. Clicking an address shows the full audit trail: every note, every attempt, every outcome."

---

## Segment 5 — Ops Dashboard: Multi-Seed Results + Emissions Toggle (30 seconds)

1. Navigate to **Ops Dashboard** tab
2. Point to the **multi-seed strip** at top: "20 seeds, 95% CI"
3. Show the **error-bar charts** — Baseline vs Prototype for reliability and repeat failure rate
4. Point to the **reliability diagram** panel (calibration)
5. Toggle the **emissions comparison** — show Mode A (flat) vs Mode B (responsive-volume, shows real saving)

> **Narration:** "Results aren't from a single lucky run — they're averaged across 20 random seeds with 95% confidence intervals. And the reliability diagram proves the confidence scores actually mean something: High-confidence dispatches succeed 88% of the time."

---

## Segment 6 — Live Edge Case Demo (30 seconds)

1. Navigate to **Edge Case Demo** tab
2. Click **Case #2: Stale Note Failure**
3. Show the result: confidence score ~0.5, Medium band — "Gate code changed, contradictions pulled it down"
4. Click **Case #6: Duplicate Merge Review**
5. Show: two addresses flagged, `decision: PENDING`, the test instruction for ops to action

> **Narration:** "Edge Case #2 demonstrates stale-note detection — the system downgrades confidence automatically. Edge Case #6 shows the merge workflow: the system flags near-duplicates but never auto-merges. An ops manager must explicitly decide."

---

## Segment 7 — Close (10 seconds)

> **Narration:**  
> "Across 20 seeds, the prototype reduced repeat failure rate from 51% to 37% and improved first-attempt reliability to 71% — meeting all three primary targets. The remaining gap: the data is synthetic, and a real pilot with live addresses would sharpen these numbers. The system is ready for that pilot."

*Show:* The multi-seed metrics table (Ops Dashboard or a final slide with the headline numbers).

---

## Recording Instructions

```bash
# Windows Game Bar (no install needed):
Win + G → Start Recording → do demo → Stop

# OBS Studio:
# Set source to "Window Capture" → select browser window
# Output: MP4, H.264, 1920×1080, ~3500 kbps

# Export to: demo/demo_video.mp4
```

**Target file size:** < 200MB for a 3:30 recording at 1080p  
**Trim silence** at start/end before submitting
