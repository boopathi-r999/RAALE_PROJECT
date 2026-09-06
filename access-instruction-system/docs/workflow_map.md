# Workflow Map

## 1. Dispatch Step
1. Dispatch system looks up `address_id` before an attempt.
2. System calls `GET /dispatch/{address_id}`.
3. API retrieves all `AccessNote` records for the given address.
4. If no notes exist, returns `note=None` with "Low confidence / no verified note".
5. If notes exist, calculate `confidence_score` for each note based on confirmations, contradictions, and time decay.
6. Return the highest scoring note to the Driver UI along with the categorized `confidence_label`.

## 2. Driver Attempt Step
1. Driver sees the instruction and the confidence band.
2. Driver makes the physical delivery attempt.
3. Driver logs the outcome (SUCCESS, FAILED, or RTO).
4. System calls `POST /attempts` with the `outcome` and the `used_note_id`.

## 3. Feedback Loop & Outcome Capture
1. **If SUCCESS and Note Used**: 
   - `confirmation_count` increments. 
   - `last_confirmed_at` updates to now.
2. **If FAILED/RTO and Note Used**: 
   - `contradiction_count` increments, rapidly degrading future confidence.
3. **If SUCCESS and NO Note Used (Cold Start)**: 
   - System prompts driver to log a new note.
   - Driver enters text -> `POST /notes` creates a new note with `source=DRIVER_LOGGED` and initial `confirmation_count=1`.

## 4. Customer Confirmation (Out of Band)
1. System sends SMS link to customer to confirm address details.
2. Customer confirms the existing note.
3. System calls `POST /notes/{note_id}/confirm` with `source=CUSTOMER_CONFIRMED`.
4. `confirmation_count` gets a +3 boost, creating an immediately high-confidence instruction for the next driver.
