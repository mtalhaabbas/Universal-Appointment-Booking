import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.businesses.models import BusinessType, Business, BusinessHours
from apps.services.models import Service, ServiceResourceRequirement
from apps.resources.models import Staff, Resource
from apps.availability.models import StaffAvailability
from apps.bookings.models import Booking
from apps.bookings.services import BookingService
from apps.notifications.models import NotificationTemplate, NotificationDelivery, OutboxEvent
from apps.notifications.services import NotificationDispatcher, OutboxProcessor
from apps.integrations.models import CalendarConnection, CalendarEventMapping
from apps.integrations.calendar_adapter import CalendarSyncService, MockCalendarAdapter


class AutomationsAndIntegrationsTestCase(TestCase):
    def setUp(self):
        self.btype = BusinessType.objects.create(name='Clinic', slug='clinic')
        self.business = Business.objects.create(
            name='Automation Clinic',
            slug='automation-clinic',
            business_type=self.btype,
            time_zone='UTC',
            contact_email='admin@autoclinic.local',
            settings={'min_notice_hours': 0, 'max_advance_days': 30, 'slot_interval_minutes': 15, 'cancellation_deadline_hours': 24}
        )
        for d in range(7):
            BusinessHours.objects.create(
                business=self.business, day_of_week=d,
                open_time=datetime.time(9, 0), close_time=datetime.time(17, 0), is_closed=False
            )

        self.doctor = Staff.objects.create(business=self.business, name='Dr. Integration', is_active=True)
        for d in range(7):
            StaffAvailability.objects.create(
                staff=self.doctor, day_of_week=d,
                start_time=datetime.time(9, 0), end_time=datetime.time(17, 0)
            )

        self.service = Service.objects.create(
            business=self.business, name='Virtual Consult', slug='virtual-consult',
            duration_minutes=30, buffer_time_minutes=0, capacity=1, price=Decimal('75.00'),
            booking_policies={'requires_staff': True, 'requires_resource': False}
        )
        self.service.qualified_staff.set([self.doctor])

        # Notification Template
        self.email_template = NotificationTemplate.objects.create(
            business=self.business,
            event_type='booking.confirmed',
            channel='email',
            subject='Confirmed: {{service_name}} for {{customer_name}}',
            template_body='Hello {{customer_name}}, your appointment {{reference}} for {{service_name}} is confirmed.'
        )

        # Calendar Connection
        self.calendar_conn = CalendarConnection.objects.create(
            business=self.business,
            calendar_provider='mock',
            calendar_id='primary',
            is_active=True
        )

    def test_outbox_event_emitted_and_processed(self):
        """Validates Transactional Outbox event generation and processing"""
        booking_svc = BookingService(self.business)
        start_dt = timezone.now() + datetime.timedelta(days=1)
        start_dt = start_dt.replace(hour=10, minute=0, second=0, microsecond=0)

        # Create booking -> Emits outbox event atomically
        booking, created = booking_svc.create_booking(
            service=self.service,
            start_time=start_dt,
            customer_data={'name': 'Jane Integration', 'email': 'jane@integration.local', 'phone': '+15550001111'}
        )
        self.assertTrue(created)

        # Verify OutboxEvent exists with 'pending' status
        outbox_event = OutboxEvent.objects.filter(business=self.business, status='pending').first()
        self.assertIsNotNone(outbox_event)
        self.assertEqual(outbox_event.event_type, 'booking.confirmed')
        self.assertEqual(outbox_event.payload['customer_name'], 'Jane Integration')
        self.assertEqual(outbox_event.payload['booking_reference'], booking.booking_reference)

        # Process outbox
        processed_count = OutboxProcessor.process_pending_events()
        self.assertGreater(processed_count, 0)

        outbox_event.refresh_from_db()
        self.assertEqual(outbox_event.status, 'delivered')
        self.assertIsNotNone(outbox_event.processed_at)

    def test_notification_template_rendering(self):
        """Validates placeholder replacement in notification templates"""
        context = {
            'customer_name': 'Alice Smith',
            'service_name': 'Virtual Consult',
            'reference': 'BK-123456'
        }
        rendered_subject = NotificationDispatcher.render_template(self.email_template.subject, context)
        rendered_body = NotificationDispatcher.render_template(self.email_template.template_body, context)

        self.assertEqual(rendered_subject, 'Confirmed: Virtual Consult for Alice Smith')
        self.assertEqual(rendered_body, 'Hello Alice Smith, your appointment BK-123456 for Virtual Consult is confirmed.')

    def test_calendar_sync_service(self):
        """Validates CalendarSyncService and MockCalendarAdapter event creation"""
        booking_svc = BookingService(self.business)
        start_dt = timezone.now() + datetime.timedelta(days=2)
        start_dt = start_dt.replace(hour=14, minute=0, second=0, microsecond=0)

        booking, _ = booking_svc.create_booking(
            service=self.service,
            start_time=start_dt,
            customer_data={'name': 'Calendar Client', 'email': 'cal@test.local'}
        )

        CalendarSyncService.sync_booking_created(booking)

        mapping = CalendarEventMapping.objects.filter(booking=booking).first()
        self.assertIsNotNone(mapping)
        self.assertTrue(mapping.external_event_id.startswith('mock_evt_'))
        self.assertEqual(mapping.sync_state, 'synced')
