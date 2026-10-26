# WhatsApp Cloud API & Calendar Integration Guide

## 1. Official WhatsApp Business Cloud API

The engine provides an official WhatsApp Business Cloud API integration layer.

### Webhook Verification (GET)
Meta's Cloud API verifies endpoints by sending a GET request with `hub.mode`, `hub.verify_token`, and `hub.challenge`.
- **Endpoint**: `/api/v1/integrations/whatsapp/webhook/`
- **Verify Token**: Configured via `WHATSAPP_VERIFY_TOKEN` (default: `universal_booking_verify_token_2026`).

### Inbound Message Handling (POST)
When a customer sends a message on WhatsApp:
1. The message payload is received and checked for idempotency using the message ID in `WebhookLog`.
2. The message text is parsed to extract business vertical, service, date, and intent.
3. The bot queries `AvailabilityService` for real-time open slots.
4. The appointment is created using `BookingService` with identical ACID transactions and concurrency checks as the web portal.

### Mock & Live Modes
- In local development or demonstrations without live Meta app credentials, `WHATSAPP_MOCK_MODE=True` simulates conversational replies and logs outbound dispatches.
- In production, set `WHATSAPP_MOCK_MODE=False`, `WHATSAPP_API_TOKEN`, and `WHATSAPP_PHONE_NUMBER_ID` to deliver real WhatsApp messages via Meta Graph API v19.0.

---

## 2. Google Calendar Synchronization

The engine uses an abstract provider pattern (`AbstractCalendarProvider`):
- [`calendar_adapter.py`](file:///Users/talha/Downloads/github/Universal-Appointment-Booking/backend/apps/integrations/calendar_adapter.py)

### Supported Operations:
- `create_event`: Creates an event on the external calendar when a booking is confirmed.
- `update_event`: Adjusts calendar event times when an appointment is rescheduled.
- `delete_event`: Removes event when a booking is cancelled.
- **Mapping Record**: Stored in `CalendarEventMapping` linking internal `Booking` to `external_event_id` with `sync_state`.

### Mock Provider for CI/CD and Demos
To ensure zero friction during local testing, `MockCalendarAdapter` generates realistic `mock_evt_...` identifiers and logs lifecycle events.

To activate live Google Calendar sync:
1. Provide `GOOGLE_CALENDAR_CLIENT_ID` and `GOOGLE_CALENDAR_CLIENT_SECRET`.
2. Set `CALENDAR_MOCK_MODE=False`.
3. Authorize via OAuth2 callback to store `access_token` and `refresh_token` in `CalendarConnection`.
