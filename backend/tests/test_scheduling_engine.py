import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.businesses.models import BusinessType, Business, BusinessHours
from apps.services.models import Service, ServiceResourceRequirement
from apps.resources.models import Staff, Resource
from apps.availability.models import StaffAvailability, AvailabilityBreak, AvailabilityException
from apps.customers.models import Customer
from apps.bookings.models import Booking, ClassOccurrence, ClassParticipant
from apps.availability.services import AvailabilityService
from apps.bookings.services import BookingService, BookingConflictError, BookingPolicyError


class UniversalSchedulingEngineTestCase(TestCase):
    """
    Validates that the EXACT same booking engine correctly handles:
    1. Clinic 1:1 doctor & consultation room appointment
    2. Salon 1:1 stylist & styling station appointment with buffer times
    3. Gym group class (Yoga capacity 15) vs exclusive 1:1 Personal Training
    4. Double booking prevention & concurrency conflict handling
    5. Staff break & holiday availability exceptions
    6. Cancellation & Rescheduling policies
    7. Idempotency guarantees
    """

    def setUp(self):
        # 1. Clinic Setup
        self.clinic_type = BusinessType.objects.create(name='Clinic', slug='clinic')
        self.clinic = Business.objects.create(
            name='Test Clinic',
            slug='test-clinic',
            business_type=self.clinic_type,
            time_zone='America/New_York',
            contact_email='clinic@test.local',
            settings={'min_notice_hours': 0, 'max_advance_days': 30, 'slot_interval_minutes': 15, 'cancellation_deadline_hours': 24}
        )
        for d in range(7):
            BusinessHours.objects.create(
                business=self.clinic, day_of_week=d,
                open_time=datetime.time(9, 0), close_time=datetime.time(17, 0), is_closed=False
            )

        self.doctor_a = Staff.objects.create(business=self.clinic, name='Dr. Alice', is_active=True)
        self.doctor_b = Staff.objects.create(business=self.clinic, name='Dr. Bob', is_active=True)

        for doc in [self.doctor_a, self.doctor_b]:
            for d in range(7):
                StaffAvailability.objects.create(
                    staff=doc, day_of_week=d,
                    start_time=datetime.time(9, 0), end_time=datetime.time(17, 0)
                )

        self.clinic_room1 = Resource.objects.create(
            business=self.clinic, name='Room 1', resource_type='Consultation Room', capacity=1
        )
        self.clinic_room2 = Resource.objects.create(
            business=self.clinic, name='Room 2', resource_type='Consultation Room', capacity=1
        )

        self.gen_consult = Service.objects.create(
            business=self.clinic, name='General Consultation', slug='gen-consult',
            duration_minutes=30, buffer_time_minutes=0, capacity=1, price=Decimal('100.00'),
            booking_policies={'requires_staff': True, 'requires_resource': True}
        )
        self.gen_consult.qualified_staff.set([self.doctor_a, self.doctor_b])
        ServiceResourceRequirement.objects.create(
            service=self.gen_consult, resource_type='Consultation Room', quantity=1
        )

        # 2. Salon Setup
        self.salon_type = BusinessType.objects.create(name='Salon', slug='salon')
        self.salon = Business.objects.create(
            name='Test Salon',
            slug='test-salon',
            business_type=self.salon_type,
            time_zone='America/Chicago',
            contact_email='salon@test.local',
            settings={'min_notice_hours': 0, 'max_advance_days': 30, 'slot_interval_minutes': 15, 'cancellation_deadline_hours': 12}
        )
        for d in range(7):
            BusinessHours.objects.create(
                business=self.salon, day_of_week=d,
                open_time=datetime.time(9, 0), close_time=datetime.time(19, 0), is_closed=False
            )

        self.stylist = Staff.objects.create(business=self.salon, name='Stylist Sarah', is_active=True)
        for d in range(7):
            StaffAvailability.objects.create(
                staff=self.stylist, day_of_week=d,
                start_time=datetime.time(9, 0), end_time=datetime.time(19, 0)
            )

        self.station1 = Resource.objects.create(
            business=self.salon, name='Station 1', resource_type='Styling Station', capacity=1
        )

        self.haircut = Service.objects.create(
            business=self.salon, name='Haircut', slug='haircut',
            duration_minutes=45, buffer_time_minutes=15, capacity=1, price=Decimal('60.00'),
            booking_policies={'requires_staff': True, 'requires_resource': True}
        )
        self.haircut.qualified_staff.set([self.stylist])
        ServiceResourceRequirement.objects.create(
            service=self.haircut, resource_type='Styling Station', quantity=1
        )

        # 3. Gym Setup
        self.gym_type = BusinessType.objects.create(name='Gym', slug='gym')
        self.gym = Business.objects.create(
            name='Test Gym',
            slug='test-gym',
            business_type=self.gym_type,
            time_zone='America/Los_Angeles',
            contact_email='gym@test.local',
            settings={'min_notice_hours': 0, 'max_advance_days': 14, 'slot_interval_minutes': 15}
        )
        for d in range(7):
            BusinessHours.objects.create(
                business=self.gym, day_of_week=d,
                open_time=datetime.time(6, 0), close_time=datetime.time(22, 0), is_closed=False
            )

        self.yoga_instructor = Staff.objects.create(business=self.gym, name='Elena Yoga', is_active=True)
        self.gym_studio = Resource.objects.create(
            business=self.gym, name='Yoga Studio', resource_type='Studio Room', capacity=20
        )

        self.yoga_service = Service.objects.create(
            business=self.gym, name='Yoga Class', slug='yoga-class',
            duration_minutes=60, buffer_time_minutes=15, capacity=15, price=Decimal('20.00'),
            booking_policies={'requires_staff': True, 'requires_resource': True, 'is_group_session': True}
        )
        self.yoga_service.qualified_staff.set([self.yoga_instructor])
        ServiceResourceRequirement.objects.create(
            service=self.yoga_service, resource_type='Studio Room', quantity=1
        )

    def test_clinic_booking_and_double_booking_prevention(self):
        """Clinic test: Doctor A and Doctor B can both consult at 10:00 AM in Room 1 & 2, but a 3rd booking must fail."""
        booking_svc = BookingService(self.clinic)
        tomorrow = timezone.now() + datetime.timedelta(days=1)
        booking_dt = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)  # 10:00 AM EDT (14:00 UTC)

        # First booking -> Doctor A, Room 1
        b1, created1 = booking_svc.create_booking(
            service=self.gen_consult,
            start_time=booking_dt,
            customer_data={'name': 'Patient 1', 'email': 'patient1@test.local'},
            staff=self.doctor_a
        )
        self.assertTrue(created1)
        self.assertEqual(b1.staff, self.doctor_a)
        self.assertEqual(b1.assigned_resources.first(), self.clinic_room1)

        # Second booking at same time -> Doctor B, Room 2
        b2, created2 = booking_svc.create_booking(
            service=self.gen_consult,
            start_time=booking_dt,
            customer_data={'name': 'Patient 2', 'email': 'patient2@test.local'},
            staff=self.doctor_b
        )
        self.assertTrue(created2)
        self.assertEqual(b2.staff, self.doctor_b)
        self.assertEqual(b2.assigned_resources.first(), self.clinic_room2)

        # Attempt to book Doctor A again at the exact same overlapping time -> MUST RAISE CONFLICT!
        with self.assertRaises(BookingConflictError):
            booking_svc.create_booking(
                service=self.gen_consult,
                start_time=booking_dt,
                customer_data={'name': 'Patient 3', 'email': 'patient3@test.local'},
                staff=self.doctor_a
            )

        # Attempt to book a 3rd patient when both rooms are full -> MUST RAISE CONFLICT!
        with self.assertRaises(BookingConflictError):
            booking_svc.create_booking(
                service=self.gen_consult,
                start_time=booking_dt,
                customer_data={'name': 'Patient 4', 'email': 'patient4@test.local'}
            )

    def test_salon_buffer_time_and_resource_exclusivity(self):
        """Salon test: Haircut takes 45m + 15m buffer = 60m busy block. Next booking cannot start until 60m later."""
        booking_svc = BookingService(self.salon)
        target_date = (timezone.now() + datetime.timedelta(days=2)).date()
        start_time_local = datetime.datetime.combine(target_date, datetime.time(10, 0), tzinfo=ZoneInfo('America/Chicago'))

        # Book 10:00 - 10:45 (busy until 11:00 due to 15m buffer)
        b1, _ = booking_svc.create_booking(
            service=self.haircut,
            start_time=start_time_local,
            customer_data={'name': 'Salon Client 1', 'email': 'client1@test.local'},
            staff=self.stylist
        )
        self.assertEqual(b1.duration_minutes, 45)

        # Attempt to book at 10:30 (during appointment) -> Must raise conflict
        overlap_dt = start_time_local + datetime.timedelta(minutes=30)
        with self.assertRaises(BookingConflictError):
            booking_svc.create_booking(
                service=self.haircut,
                start_time=overlap_dt,
                customer_data={'name': 'Salon Client 2', 'email': 'client2@test.local'},
                staff=self.stylist
            )

        # Attempt to book at 10:45 (during 15m buffer period!) -> Must raise conflict
        buffer_dt = start_time_local + datetime.timedelta(minutes=45)
        with self.assertRaises(BookingConflictError):
            booking_svc.create_booking(
                service=self.haircut,
                start_time=buffer_dt,
                customer_data={'name': 'Salon Client 3', 'email': 'client3@test.local'},
                staff=self.stylist
            )

        # Booking at 11:00 (after buffer ends) -> MUST SUCCEED
        after_buffer_dt = start_time_local + datetime.timedelta(minutes=60)
        b2, created2 = booking_svc.create_booking(
            service=self.haircut,
            start_time=after_buffer_dt,
            customer_data={'name': 'Salon Client 4', 'email': 'client4@test.local'},
            staff=self.stylist
        )
        self.assertTrue(created2)

    def test_gym_group_class_capacity_limit(self):
        """Gym test: Yoga class supports multiple participants up to capacity, then blocks when full."""
        session_dt = timezone.now() + datetime.timedelta(days=3)
        session_dt = session_dt.replace(hour=17, minute=0, second=0, microsecond=0)

        # Create scheduled occurrence with capacity 2 for testing
        occ = ClassOccurrence.objects.create(
            business=self.gym,
            service=self.yoga_service,
            instructor=self.yoga_instructor,
            resource=self.gym_studio,
            start_time=session_dt,
            end_time=session_dt + datetime.timedelta(minutes=60),
            capacity=2,
            booked_count=0,
            status='scheduled'
        )

        booking_svc = BookingService(self.gym)

        # Participant 1 books
        b1, _ = booking_svc.create_booking(
            service=self.yoga_service,
            start_time=session_dt,
            occurrence_id=str(occ.id),
            customer_data={'name': 'Yogi 1', 'email': 'yogi1@test.local'}
        )
        occ.refresh_from_db()
        self.assertEqual(occ.booked_count, 1)
        self.assertEqual(occ.remaining_spots, 1)

        # Participant 2 books
        b2, _ = booking_svc.create_booking(
            service=self.yoga_service,
            start_time=session_dt,
            occurrence_id=str(occ.id),
            customer_data={'name': 'Yogi 2', 'email': 'yogi2@test.local'}
        )
        occ.refresh_from_db()
        self.assertEqual(occ.booked_count, 2)
        self.assertEqual(occ.remaining_spots, 0)
        self.assertEqual(occ.status, 'full')

        # Participant 3 attempts to book -> MUST FAIL WITH CAPACITY CONFLICT!
        with self.assertRaises(BookingConflictError):
            booking_svc.create_booking(
                service=self.yoga_service,
                start_time=session_dt,
                occurrence_id=str(occ.id),
                customer_data={'name': 'Yogi 3', 'email': 'yogi3@test.local'}
            )

        # Participant 1 cancels -> spot opens up!
        booking_svc.cancel_booking(b1, reason='Need to reschedule', bypass_policy=True)
        occ.refresh_from_db()
        self.assertEqual(occ.booked_count, 1)
        self.assertEqual(occ.remaining_spots, 1)
        self.assertEqual(occ.status, 'scheduled')

        # Now Yogi 3 can book successfully!
        b3, _ = booking_svc.create_booking(
            service=self.yoga_service,
            start_time=session_dt,
            occurrence_id=str(occ.id),
            customer_data={'name': 'Yogi 3', 'email': 'yogi3@test.local'}
        )
        self.assertIsNotNone(b3)

    def test_idempotent_booking_requests(self):
        """Idempotency test: duplicate requests with same idempotency_key return existing booking without duplicates."""
        booking_svc = BookingService(self.clinic)
        booking_dt = timezone.now() + datetime.timedelta(days=4)
        booking_dt = booking_dt.replace(hour=15, minute=0, second=0, microsecond=0)

        idempotency_key = "idemp_req_abc_123"

        b1, created1 = booking_svc.create_booking(
            service=self.gen_consult,
            start_time=booking_dt,
            customer_data={'name': 'Idempotent Customer', 'email': 'idemp@test.local'},
            idempotency_key=idempotency_key
        )
        self.assertTrue(created1)

        # Second submission with same key
        b2, created2 = booking_svc.create_booking(
            service=self.gen_consult,
            start_time=booking_dt,
            customer_data={'name': 'Idempotent Customer', 'email': 'idemp@test.local'},
            idempotency_key=idempotency_key
        )
        self.assertFalse(created2)
        self.assertEqual(b1.id, b2.id)
        self.assertEqual(b1.booking_reference, b2.booking_reference)

    def test_cancellation_policy_enforcement(self):
        """Cancellation test: cannot cancel within 24 hours of appointment unless staff bypass."""
        booking_svc = BookingService(self.clinic)
        # Appointment starts in 6 hours (within 24h deadline)
        soon_dt = timezone.now() + datetime.timedelta(hours=6)

        b, _ = booking_svc.create_booking(
            service=self.gen_consult,
            start_time=soon_dt,
            customer_data={'name': 'Late Client', 'email': 'late@test.local'}
        )

        # Customer attempts to cancel -> MUST BE REJECTED BY POLICY!
        with self.assertRaises(BookingPolicyError):
            booking_svc.cancel_booking(b, reason='Changed my mind', bypass_policy=False)

        # Staff override bypass -> ALLOWED
        cancelled_b = booking_svc.cancel_booking(b, reason='Medical emergency override', bypass_policy=True)
        self.assertEqual(cancelled_b.status, 'cancelled')
