# n8n Automation Integration Guide

The Universal Appointment Booking Engine includes a complete suite of generic, reusable n8n workflows designed to handle asynchronous notifications, customer communications, calendar synchronizations, and reporting.

---

## 1. Importable Workflow Suite

All workflows are located in the [`automations/n8n/`](file:///Users/talha/Downloads/github/Universal-Appointment-Booking/automations/n8n/) directory:

| File | Purpose | Trigger |
| :--- | :--- | :--- |
| `01_booking_confirmation_workflow.json` | Dispatches email & WhatsApp confirmations | Webhook (`POST /webhook/booking-events`) |
| `02_appointment_reminder_workflow.json` | Sends 24-hour advance appointment reminders | Schedule (Hourly Cron) |
| `03_booking_rescheduling_workflow.json` | Notifies customer of rescheduled date/time | Webhook (`POST /webhook/booking-events-reschedule`) |
| `04_booking_cancellation_workflow.json` | Sends cancellation notices & releases spots | Webhook (`POST /webhook/booking-events-cancel`) |
| `05_delivery_retry_workflow.json` | Exponential backoff retry handler for failed outbox events | Schedule (Every 15 minutes) |
| `06_daily_summary_workflow.json` | Aggregates daily practitioner schedule briefings | Schedule (Daily at 07:00 AM) |

---

## 2. How to Import Workflows into n8n

1. Start n8n using Docker Compose:
   ```bash
   docker compose up -d n8n
   ```
2. Open n8n in your browser:
   ```
   http://localhost:5678/
   ```
3. In n8n:
   - Click **Workflows** &rarr; **Add Workflow** &rarr; **Import from File**.
   - Select any workflow JSON file from `automations/n8n/`.
   - Click **Activate Workflow**.

---

## 3. Standardized Outbox Event Payload

All booking events emitted from the Transactional Outbox follow this standardized JSON schema:

```json
{
  "event_id": "evt_4a9f2bc81e02",
  "event_type": "booking.confirmed",
  "business_id": "b3f07a21-9922-4a0b-9cb7-7ef93844db31",
  "business_slug": "demo-health-clinic",
  "business_name": "Demo Health Clinic",
  "booking_id": "893c5d72-9ea3-4d44-a035-7c2d1bfa9801",
  "booking_reference": "BK-9A23E1",
  "service_id": "c1a2f3e4-5b6c-7d8e-9f0a-1b2c3d4e5f6a",
  "service_name": "General Consultation",
  "staff_id": "f8a7b6c5-d4e3-2f1a-0b9c-8d7e6f5a4b3c",
  "staff_name": "Doctor A (Dr. Alice Smith)",
  "customer_name": "Jane Doe",
  "customer_email": "jane.doe@example.com",
  "customer_phone": "+15551234567",
  "starts_at": "2026-11-02T14:00:00Z",
  "ends_at": "2026-11-02T14:30:00Z",
  "status": "confirmed",
  "timezone": "America/New_York",
  "notification_channels": ["email", "whatsapp"],
  "timestamp": "2026-10-26T17:40:00Z"
}
```

---

## 4. Processing the Outbox

The engine includes a background outbox processor:

```bash
python backend/manage.py process_outbox --limit 50
```

When called, it reads pending `OutboxEvent` records, delivers them to the n8n webhook URL (`N8N_WEBHOOK_URL`), executes notification dispatchers, and updates event statuses to `delivered` or `failed` with retry tracking.
