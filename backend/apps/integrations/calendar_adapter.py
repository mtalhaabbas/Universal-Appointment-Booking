import uuid
import logging
import datetime
from abc import ABC, abstractmethod
from django.conf import settings
from django.utils import timezone

from apps.bookings.models import Booking
from apps.integrations.models import CalendarConnection, CalendarEventMapping

logger = logging.getLogger(__name__)


class AbstractCalendarProvider(ABC):
    """
    Standard interface for external calendar providers (Google Calendar, Outlook, etc.)
    """

    @abstractmethod
    def create_event(self, booking: Booking, calendar_id: str) -> str:
        """Creates event on external calendar and returns external event ID."""
        pass

    @abstractmethod
    def update_event(self, booking: Booking, external_event_id: str, calendar_id: str) -> bool:
        """Updates event on external calendar."""
        pass

    @abstractmethod
    def delete_event(self, external_event_id: str, calendar_id: str) -> bool:
        """Removes event from external calendar."""
        pass


class MockCalendarAdapter(AbstractCalendarProvider):
    """
    Production-grade mock provider used for demonstrations, CI/CD, and local testing
    when live Google Cloud credentials are not configured.
    """

    def create_event(self, booking: Booking, calendar_id: str) -> str:
        external_id = f"mock_evt_{uuid.uuid4().hex[:14]}"
        logger.info(
            f"[MOCK GCAL] Created event {external_id} for {booking.booking_reference}: "
            f"'{booking.service.name}' on {booking.start_time.isoformat()} in calendar '{calendar_id}'"
        )
        return external_id

    def update_event(self, booking: Booking, external_event_id: str, calendar_id: str) -> bool:
        logger.info(
            f"[MOCK GCAL] Updated event {external_event_id} for {booking.booking_reference} "
            f"new start: {booking.start_time.isoformat()} in calendar '{calendar_id}'"
        )
        return True

    def delete_event(self, external_event_id: str, calendar_id: str) -> bool:
        logger.info(f"[MOCK GCAL] Deleted event {external_event_id} from calendar '{calendar_id}'")
        return True


class GoogleCalendarAdapter(AbstractCalendarProvider):
    """
    Live Google Calendar integration using Google Calendar v3 API.
    Activated when CALENDAR_MOCK_MODE=False and OAuth credentials are provided.
    """

    def __init__(self, connection: CalendarConnection):
        self.connection = connection

    def create_event(self, booking: Booking, calendar_id: str) -> str:
        if getattr(settings, 'CALENDAR_MOCK_MODE', True) or not self.connection.access_token:
            return MockCalendarAdapter().create_event(booking, calendar_id)

        # Real Google Calendar API Call
        import requests
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
        headers = {
            "Authorization": f"Bearer {self.connection.access_token}",
            "Content-Type": "application/json"
        }
        event_body = {
            "summary": f"{booking.service.name} - {booking.customer.name}",
            "description": f"Booking Ref: {booking.booking_reference}\nPractitioner: {booking.staff.name if booking.staff else 'N/A'}\nNotes: {booking.notes}",
            "start": {"dateTime": booking.start_time.isoformat()},
            "end": {"dateTime": booking.end_time.isoformat()},
        }
        resp = requests.post(url, headers=headers, json=event_body, timeout=10)
        resp.raise_for_status()
        return resp.json().get('id')

    def update_event(self, booking: Booking, external_event_id: str, calendar_id: str) -> bool:
        if getattr(settings, 'CALENDAR_MOCK_MODE', True) or not self.connection.access_token:
            return MockCalendarAdapter().update_event(booking, external_event_id, calendar_id)

        import requests
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{external_event_id}"
        headers = {
            "Authorization": f"Bearer {self.connection.access_token}",
            "Content-Type": "application/json"
        }
        event_body = {
            "summary": f"{booking.service.name} - {booking.customer.name}",
            "start": {"dateTime": booking.start_time.isoformat()},
            "end": {"dateTime": booking.end_time.isoformat()},
        }
        resp = requests.patch(url, headers=headers, json=event_body, timeout=10)
        return resp.status_code == 200

    def delete_event(self, external_event_id: str, calendar_id: str) -> bool:
        if getattr(settings, 'CALENDAR_MOCK_MODE', True) or not self.connection.access_token:
            return MockCalendarAdapter().delete_event(external_event_id, calendar_id)

        import requests
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{external_event_id}"
        headers = {"Authorization": f"Bearer {self.connection.access_token}"}
        resp = requests.delete(url, headers=headers, timeout=10)
        return resp.status_code in (200, 204, 404)


class CalendarSyncService:
    """
    Coordinates internal bookings with connected calendars.
    """

    @classmethod
    def sync_booking_created(cls, booking: Booking):
        connections = CalendarConnection.objects.filter(
            business=booking.business,
            is_active=True
        )
        for conn in connections:
            adapter = GoogleCalendarAdapter(conn) if conn.calendar_provider == 'google' else MockCalendarAdapter()
            try:
                external_id = adapter.create_event(booking, conn.calendar_id)
                CalendarEventMapping.objects.update_or_create(
                    booking=booking,
                    calendar_connection=conn,
                    defaults={'external_event_id': external_id, 'sync_state': 'synced'}
                )
            except Exception as e:
                logger.error(f"Failed to sync booking {booking.booking_reference} to calendar: {e}")
