import datetime
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.utils import timezone

from apps.businesses.models import BusinessType, Business, BusinessHours
from apps.services.models import Service, ServiceResourceRequirement
from apps.resources.models import Staff, Resource
from apps.availability.models import StaffAvailability
from apps.bookings.models import Booking


class BookingAPITestCase(APITestCase):
    def setUp(self):
        self.clinic_type = BusinessType.objects.create(name='Clinic', slug='clinic')
        self.clinic = Business.objects.create(
            name='API Clinic',
            slug='api-clinic',
            business_type=self.clinic_type,
            time_zone='UTC',
            contact_email='api@clinic.local',
            settings={'min_notice_hours': 0, 'max_advance_days': 30, 'slot_interval_minutes': 30, 'cancellation_deadline_hours': 24}
        )
        for d in range(7):
            BusinessHours.objects.create(
                business=self.clinic, day_of_week=d,
                open_time=datetime.time(9, 0), close_time=datetime.time(17, 0), is_closed=False
            )

        self.doc = Staff.objects.create(business=self.clinic, name='Dr. Dave', is_active=True)
        for d in range(7):
            StaffAvailability.objects.create(
                staff=self.doc, day_of_week=d,
                start_time=datetime.time(9, 0), end_time=datetime.time(17, 0)
            )

        self.room = Resource.objects.create(
            business=self.clinic, name='Room 101', resource_type='Consultation Room', capacity=1
        )

        self.service = Service.objects.create(
            business=self.clinic, name='Checkup', slug='checkup',
            duration_minutes=30, buffer_time_minutes=0, capacity=1, price=Decimal('80.00'),
            booking_policies={'requires_staff': True, 'requires_resource': True}
        )
        self.service.qualified_staff.set([self.doc])
        ServiceResourceRequirement.objects.create(
            service=self.service, resource_type='Consultation Room', quantity=1
        )

        # Other Business for Tenant Isolation Test
        self.salon = Business.objects.create(
            name='API Salon',
            slug='api-salon',
            business_type=self.clinic_type,
            time_zone='UTC',
            contact_email='api@salon.local'
        )

    def test_availability_api(self):
        target_date = (timezone.now() + datetime.timedelta(days=2)).date()
        url = reverse('api-availability', kwargs={'business_slug': self.clinic.slug})
        response = self.client.get(url, {'service_id': str(self.service.id), 'date': target_date.isoformat()})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('slots', response.data)
        self.assertGreater(response.data['slots_count'], 0)
        self.assertEqual(response.data['business_slug'], self.clinic.slug)

    def test_create_booking_api(self):
        target_dt = timezone.now() + datetime.timedelta(days=2)
        target_dt = target_dt.replace(hour=11, minute=0, second=0, microsecond=0)

        url = reverse('api-booking-create', kwargs={'business_slug': self.clinic.slug})
        payload = {
            'service_id': str(self.service.id),
            'start_time': target_dt.isoformat(),
            'customer': {
                'name': 'API Test Customer',
                'email': 'customer@apitest.local',
                'phone': '+15559876543'
            },
            'source_channel': 'website',
            'notes': 'Booked via test'
        }

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('booking_reference', response.data)
        self.assertEqual(response.data['status'], 'confirmed')
        self.assertEqual(response.data['customer']['email'], 'customer@apitest.local')

        # Test duplicate booking at same time -> 409 CONFLICT
        conflict_response = self.client.post(url, payload, format='json')
        self.assertEqual(conflict_response.status_code, status.HTTP_409_CONFLICT)

    def test_tenant_isolation(self):
        """A booking made at 'api-clinic' cannot be retrieved under 'api-salon'"""
        target_dt = timezone.now() + datetime.timedelta(days=3)
        target_dt = target_dt.replace(hour=10, minute=0, second=0, microsecond=0)

        create_url = reverse('api-booking-create', kwargs={'business_slug': self.clinic.slug})
        resp = self.client.post(create_url, {
            'service_id': str(self.service.id),
            'start_time': target_dt.isoformat(),
            'customer': {'name': 'Private Patient', 'email': 'priv@patient.local'}
        }, format='json')

        booking_id = resp.data['id']

        # Fetch under correct business -> 200 OK
        correct_url = reverse('api-booking-detail', kwargs={'business_slug': self.clinic.slug, 'pk': booking_id})
        detail_resp = self.client.get(correct_url)
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        # Attempt to fetch under different business -> 404 NOT FOUND (Isolation preserved!)
        wrong_url = reverse('api-booking-detail', kwargs={'business_slug': self.salon.slug, 'pk': booking_id})
        forbidden_resp = self.client.get(wrong_url)
        self.assertEqual(forbidden_resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_whatsapp_webhook_verification(self):
        url = reverse('whatsapp-webhook')
        resp = self.client.get(url, {
            'hub.mode': 'subscribe',
            'hub.verify_token': 'universal_booking_verify_token_2026',
            'hub.challenge': 'CHALLENGE_ACCEPTED_123'
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.content.decode(), 'CHALLENGE_ACCEPTED_123')
