# 3-Minute Viva Walkthrough Script (Phase 2)

### 1. Driver View & Cold Start (45s)
- **Action**: Open tab 1 ("Driver View"). Enter a cold-start address ID like `ADDR_TEST_COLD`.
- **Talk Track**: "Our Driver View addresses last-mile logistics failures by providing access instructions before dispatch. Notice that when no note exists, the system doesn't leave an empty box or pretend everything is fine — it explicitly outputs an empty-state warning: *'No verified access note. Proceed as standard delivery.'*"
- **Action**: Click "Log Success", enter note *"Gate code 1234, ask for Security Ramesh"*, click "Save Note". Re-query `ADDR_TEST_COLD`.
- **Talk Track**: "The new note is immediately stored and assigned a Medium confidence band with evidence timestamping ('confirmed today')."

### 2. Customer Confirmation Portal (30s)
- **Action**: Switch to tab 2 ("Customer Portal"). Load `ADDR_TEST_COLD`.
- **Talk Track**: "The problem statement explicitly requires customer verification. When a customer clicks their SMS link, they can confirm or correct instructions. Customer corrections carry 3x weight (Customer-verified tag) compared to single driver logs."
- **Action**: Click "Confirm Details".

### 3. Address Explorer & Audit Trail (45s)
- **Action**: Switch to tab 3 ("Address Explorer"). Sort by "Lowest Confidence First".
- **Talk Track**: "Ops managers need complete visibility into high-risk locations. The Explorer surfaces addresses needing re-verification. Clicking 'Audit Trail' on any row opens a complete timeline showing every note version, confirm/contradiction count, and driver attempt log."
- **Action**: Click "Audit Trail" on `ADDR_7F3A62C8`. Show note versioning.

### 4. Live Edge Case Demonstrator (30s)
- **Action**: Switch to tab 5 ("Edge Case Demo"). Click **Case #2 (Stale Note Failure)**.
- **Talk Track**: "During a viva, we can run any of our 5 pytest edge cases live. Watch Case #2: a previously high-confidence note fails 4 times (e.g. gate code rotated). The Laplace + time-decay engine automatically drags the confidence down to Medium/Low, proving our uncertainty model doesn't give false confidence."

### 5. Ops Dashboard & Metrics Strip (30s)
- **Action**: Switch to tab 4 ("Ops Dashboard"). Show Target vs Measured strip and Chart.js bar charts.
- **Talk Track**: "Over our 90-day simulation of 1000 deliveries across 200 addresses, the prototype dropped repeat failures from 51.3% to 36.3%, and reduced cost per successful delivery from Rs. 70.55 to Rs. 56.02, using explicit assumptions of Rs. 40/attempt."
