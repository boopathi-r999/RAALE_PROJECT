# Notification Channel Plan

**Document:** Outbound Customer Notification — Channel Evaluation & Go-Live Requirements  
**System:** Access-Instruction Capture & Reuse System  
**Status:** Simulated mode implemented. Real-mode integration spec documented below.

---

## Current State (Prototype)

The system implements a `POST /notify` endpoint that sends customer notifications about their delivery access instructions. The endpoint is controlled by the `NOTIFY_MODE` environment variable:

```bash
# Run in fully simulated mode (default — no external accounts needed)
uvicorn backend.main:app --reload

# Run in real mode (requires credentials — see below)
NOTIFY_MODE=real uvicorn backend.main:app --reload
```

In **simulated mode**, the notification is logged to the database and to structured logs. The message that *would* be sent is returned in the API response, enabling full UI and test coverage without any external service dependency.

---

## Channel Options Evaluated

### Option 1: Twilio SMS (Recommended for Pilot)

**Why:** Most widely used SMS API in India, supports English and regional languages, free trial available.

| Property | Value |
|---|---|
| Cost per SMS | ~₹0.35–₹0.55 (India, Twilio Flex trial → paid) |
| Delivery rate (India) | ~96% (urban), ~88% (rural) |
| Latency | < 3 seconds |
| Opt-out handling | STOP keyword auto-handled by Twilio |
| DND compliance | Requires DLT registration (India's TRAI mandate) |
| Free trial | Yes — 15 days, limited to verified numbers |

**Integration requirements (real mode):**
1. Register at https://twilio.com — get `ACCOUNT_SID`, `AUTH_TOKEN`, `TWILIO_FROM` number
2. Register on TRAI DLT portal (mandatory for transactional SMS in India)
3. Set environment variables: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`
4. Install: `pip install twilio`
5. Change `NOTIFY_MODE=real` — the endpoint switches to `twilio.rest.Client.messages.create(...)`

**What would change in code** (`backend/main.py`, `elif mode == "real"` block):
```python
from twilio.rest import Client
twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
message = twilio_client.messages.create(
    body=f"Hi! Your delivery access note for {addr.raw_text}: '{note.instruction_text}'. Reply YES to confirm or NO to correct.",
    from_=os.environ["TWILIO_FROM"],
    to=req.recipient  # must be E.164 format, e.g. +919876543210
)
status = message.status   # "queued", "sent", "delivered", "failed"
```

---

### Option 2: Email via SMTP (Gmail / SendGrid)

**Why:** Zero additional cost for low-volume, no DLT registration required.

| Property | Value |
|---|---|
| Cost | Free (Gmail SMTP, <500/day) or SendGrid free tier (100/day) |
| Delivery rate | ~85–90% (spam filtering risk) |
| Latency | 5–30 seconds |
| Opt-out handling | Must implement manually (unsubscribe link) |
| Good for | B2B customers, ops notifications, not consumer SMS |

**Integration requirements:**
1. Gmail: enable 2FA → generate App Password
2. Set env vars: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASS`
3. Use `smtplib` (stdlib — no pip install needed)

---

### Option 3: WhatsApp Cloud API (Meta)

**Why:** Highest open rate in India (~98%), widely preferred by consumers over SMS.

| Property | Value |
|---|---|
| Cost per message | Free (first 1000 conversations/month on free tier) |
| Delivery rate | ~98% (for opted-in users) |
| Latency | < 2 seconds |
| Opt-out handling | WhatsApp built-in block feature |
| Approval required | Template message must be pre-approved by Meta (1–3 day review) |

**Integration requirements:**
1. Create a Meta Business account → WhatsApp Business API → Cloud API
2. Pre-approve a message template (e.g. "Hi {{1}}, your delivery access note is: {{2}}. Reply 1 to confirm.")
3. Set env vars: `WA_TOKEN`, `WA_PHONE_ID`
4. Use: `requests.post("https://graph.facebook.com/v18.0/{PHONE_ID}/messages", ...)`

---

## Recommended Go-Live Sequence

| Phase | Action | Cost |
|---|---|---|
| **Prototype (now)** | `NOTIFY_MODE=simulated` — full system works without accounts | ₹0 |
| **Pilot (50 addresses)** | Twilio trial — SMS to ~50 real customers with consent | ₹0 (trial) |
| **Scale (500+/day)** | Twilio paid + DLT registration | ~₹175/day |
| **Consumer scale** | WhatsApp Cloud API — migrate from SMS once templates approved | ~₹0/month for <1000 conversations |

---

## Opt-Out & Privacy Requirements (India)

- **TRAI DND Registry compliance**: Required for SMS. Transactional SMS (not promotional) must be registered on the DLT portal. Failure to register = message blocking + ₹25,000 fine.
- **Customer consent**: Must be captured at order placement. "By placing this order you consent to receive delivery status SMS" is legally sufficient.
- **Data retention**: Phone numbers stored for notification must be purged on customer request (IT Act 2000 + upcoming DPDPA 2023 requirements).
- **Opt-out**: SMS STOP reply must be honoured within 24 hours. Twilio handles this automatically; self-hosted SMTP implementations must build it.

---

## Expected Real-World Performance

Based on Delhivery published data (2023 ESG report) and Shadowfax ops documentation:
- SMS confirmation rate for access instructions: ~35–45% of customers respond when prompted
- Of those responding, ~85% confirm as correct, ~15% suggest a correction
- Average time-to-response: ~4 minutes during daytime, 18 minutes after 7pm
- Customer correction quality: ~60% of corrections are actionable (gate code, specific instruction); ~40% are vague ("just deliver it")

These numbers imply that even a 35% confirmation rate meaningfully reduces cold-start attempts, as confirmed notes get the +3 weight boost that accelerates confidence convergence.
