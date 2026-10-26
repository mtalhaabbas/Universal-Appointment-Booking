import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from apps.businesses.models import BusinessType, Business, Branch, BusinessHours, BusinessMember
from apps.services.models import Service, ServiceResourceRequirement
from apps.resources.models import Staff, Resource
from apps.availability.models import StaffAvailability, AvailabilityBreak, AvailabilityException
from apps.customers.models import Customer
from apps.bookings.models import Booking, ClassOccurrence, ClassParticipant
from apps.notifications.models import NotificationTemplate
from apps.integrations.models import CalendarConnection


class Command(BaseCommand):
    help = 'Seeds production-grade demo configurations for Clinic, Salon, and Gym verticals.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Universal Booking Engine demo data..."))

        # 1. Superuser / Admin user
        admin_user, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@universalbooking.local',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        admin_user.set_password('admin12345')
        admin_user.save()

        # 2. Business Types
        clinic_type, _ = BusinessType.objects.get_or_create(
            slug='clinic',
            defaults={
                'name': 'Healthcare Clinic',
                'description': 'Medical practices, dental offices, therapy centers, and clinical consultations.',
                'icon': 'heart-pulse',
                'default_settings': {
                    'requires_doctor': True,
                    'confirmation_mode': 'auto',
                    'cancellation_deadline_hours': 24,
                    'slot_interval_minutes': 10,
                }
            }
        )

        salon_type, _ = BusinessType.objects.get_or_create(
            slug='salon',
            defaults={
                'name': 'Beauty & Hair Salon',
                'description': 'Hair salons, spas, nail bars, and cosmetic beauty studios.',
                'icon': 'scissors',
                'default_settings': {
                    'requires_stylist': True,
                    'confirmation_mode': 'auto',
                    'cancellation_deadline_hours': 12,
                    'slot_interval_minutes': 15,
                }
            }
        )

        gym_type, _ = BusinessType.objects.get_or_create(
            slug='gym',
            defaults={
                'name': 'Gym & Fitness Center',
                'description': 'Fitness centers, yoga studios, CrossFit boxes, and athletic training facilities.',
                'icon': 'dumbbell',
                'default_settings': {
                    'supports_group_classes': True,
                    'confirmation_mode': 'auto',
                    'cancellation_deadline_hours': 6,
                    'slot_interval_minutes': 15,
                }
            }
        )

        # ---------------------------------------------------------
        # A. CLINIC: Demo Health Clinic
        # ---------------------------------------------------------
        clinic, _ = Business.objects.get_or_create(
            slug='demo-health-clinic',
            defaults={
                'name': 'Demo Health Clinic',
                'business_type': clinic_type,
                'tagline': 'Compassionate & Comprehensive Medical Care',
                'description': 'Modern outpatient clinic offering general and specialized consultations.',
                'time_zone': 'America/New_York',
                'contact_email': 'contact@demohealthclinic.com',
                'contact_phone': '+1 (555) 234-5678',
                'address': '100 Medical Center Blvd, Suite 200, New York, NY',
                'status': 'active',
                'settings': {
                    'min_notice_hours': 2,
                    'max_advance_days': 30,
                    'slot_interval_minutes': 10,
                    'cancellation_deadline_hours': 24,
                    'confirmation_mode': 'auto',
                    'allow_client_staff_selection': True,
                }
            }
        )

        BusinessMember.objects.get_or_create(
            business=clinic,
            user=admin_user,
            defaults={'role': 'owner'}
        )

        # Operating Hours: Monday to Friday 09:00 - 17:00, Saturday 09:00 - 13:00, Sunday Closed
        for day in range(7):
            is_closed = (day == 6)
            open_time = datetime.time(9, 0) if not is_closed else None
            close_time = datetime.time(13, 0) if day == 5 else (datetime.time(17, 0) if not is_closed else None)
            BusinessHours.objects.update_or_create(
                business=clinic,
                branch=None,
                day_of_week=day,
                defaults={'open_time': open_time, 'close_time': close_time, 'is_closed': is_closed}
            )

        # Clinic Services
        gen_consult, _ = Service.objects.update_or_create(
            business=clinic,
            slug='general-consultation',
            defaults={
                'name': 'General Consultation',
                'description': 'Comprehensive medical checkup and health evaluation.',
                'duration_minutes': 30,
                'price': Decimal('120.00'),
                'buffer_time_minutes': 10,
                'capacity': 1,
                'color_hex': '#0284c7',
                'booking_policies': {'requires_staff': True, 'requires_resource': True, 'resource_type': 'Consultation Room'}
            }
        )
        ServiceResourceRequirement.objects.update_or_create(
            service=gen_consult,
            resource_type='Consultation Room',
            defaults={'quantity': 1}
        )

        follow_consult, _ = Service.objects.update_or_create(
            business=clinic,
            slug='follow-up-consultation',
            defaults={
                'name': 'Follow-up Consultation',
                'description': 'Review lab results, progress monitoring, and prescription adjustments.',
                'duration_minutes': 20,
                'price': Decimal('75.00'),
                'buffer_time_minutes': 5,
                'capacity': 1,
                'color_hex': '#0ea5e9',
                'booking_policies': {'requires_staff': True, 'requires_resource': True, 'resource_type': 'Consultation Room'}
            }
        )
        ServiceResourceRequirement.objects.update_or_create(
            service=follow_consult,
            resource_type='Consultation Room',
            defaults={'quantity': 1}
        )

        # Clinic Staff: Doctor A, Doctor B
        doc_a, _ = Staff.objects.update_or_create(
            business=clinic,
            name='Doctor A (Dr. Alice Smith)',
            defaults={
                'email': 'dr.alice@demohealthclinic.com',
                'phone': '+1 (555) 234-5671',
                'title': 'General Practitioner & Internal Medicine',
                'bio': 'Board-certified internist with over 12 years of clinical diagnostic experience.',
                'color_hex': '#0284c7',
                'is_active': True,
            }
        )
        doc_a.assigned_services.set([gen_consult, follow_consult])

        doc_b, _ = Staff.objects.update_or_create(
            business=clinic,
            name='Doctor B (Dr. Bob Jones)',
            defaults={
                'email': 'dr.bob@demohealthclinic.com',
                'phone': '+1 (555) 234-5672',
                'title': 'Family Medicine Specialist',
                'bio': 'Passionate family physician focused on preventive care and chronic illness management.',
                'color_hex': '#0369a1',
                'is_active': True,
            }
        )
        doc_b.assigned_services.set([gen_consult, follow_consult])

        # Staff availability & Lunch breaks (Mon-Fri 09:00 - 17:00, lunch 12:30 - 13:30)
        for doc in [doc_a, doc_b]:
            for d in range(5):
                StaffAvailability.objects.update_or_create(
                    staff=doc,
                    day_of_week=d,
                    defaults={'start_time': datetime.time(9, 0), 'end_time': datetime.time(17, 0), 'is_active': True}
                )
                AvailabilityBreak.objects.update_or_create(
                    business=clinic,
                    staff=doc,
                    day_of_week=d,
                    defaults={'start_time': datetime.time(12, 30), 'end_time': datetime.time(13, 30), 'description': 'Physician Lunch Break'}
                )

        # Clinic Resources: Consultation Room 1, Consultation Room 2
        room1, _ = Resource.objects.update_or_create(
            business=clinic,
            name='Consultation Room 1',
            defaults={'resource_type': 'Consultation Room', 'capacity': 1, 'is_active': True}
        )
        room2, _ = Resource.objects.update_or_create(
            business=clinic,
            name='Consultation Room 2',
            defaults={'resource_type': 'Consultation Room', 'capacity': 1, 'is_active': True}
        )

        # ---------------------------------------------------------
        # B. SALON: Demo Beauty Studio
        # ---------------------------------------------------------
        salon, _ = Business.objects.get_or_create(
            slug='demo-beauty-studio',
            defaults={
                'name': 'Demo Beauty Studio',
                'business_type': salon_type,
                'tagline': 'Bespoke Hair, Color & Styling Artistry',
                'description': 'Award-winning hair and beauty sanctuary providing luxury aesthetic experiences.',
                'time_zone': 'America/Chicago',
                'contact_email': 'hello@demobeautystudio.com',
                'contact_phone': '+1 (555) 890-1234',
                'address': '450 Fashion Avenue, Chicago, IL',
                'status': 'active',
                'settings': {
                    'min_notice_hours': 1,
                    'max_advance_days': 45,
                    'slot_interval_minutes': 15,
                    'cancellation_deadline_hours': 12,
                    'confirmation_mode': 'auto',
                    'allow_client_staff_selection': True,
                }
            }
        )

        BusinessMember.objects.get_or_create(
            business=salon,
            user=admin_user,
            defaults={'role': 'owner'}
        )

        for day in range(7):
            is_closed = (day == 0)  # Salons often close Mondays
            open_time = datetime.time(9, 0) if not is_closed else None
            close_time = datetime.time(19, 0) if not is_closed else None
            BusinessHours.objects.update_or_create(
                business=salon,
                branch=None,
                day_of_week=day,
                defaults={'open_time': open_time, 'close_time': close_time, 'is_closed': is_closed}
            )

        # Salon Services: Haircut (45m), Hair Coloring (90m), Styling (30m)
        haircut, _ = Service.objects.update_or_create(
            business=salon,
            slug='haircut',
            defaults={
                'name': 'Designer Haircut',
                'description': 'Precision cut tailored to your personal aesthetic, including shampoo and blow-dry.',
                'duration_minutes': 45,
                'price': Decimal('65.00'),
                'buffer_time_minutes': 15,
                'capacity': 1,
                'color_hex': '#d97706',
                'booking_policies': {'requires_staff': True, 'requires_resource': True, 'resource_type': 'Styling Station'}
            }
        )
        ServiceResourceRequirement.objects.update_or_create(
            service=haircut,
            resource_type='Styling Station',
            defaults={'quantity': 1}
        )

        hair_color, _ = Service.objects.update_or_create(
            business=salon,
            slug='hair-coloring',
            defaults={
                'name': 'Full Hair Coloring & Balayage',
                'description': 'Custom highlights, balayage, or single-process rich multidimensional hair color.',
                'duration_minutes': 90,
                'price': Decimal('160.00'),
                'buffer_time_minutes': 15,
                'capacity': 1,
                'color_hex': '#b45309',
                'booking_policies': {'requires_staff': True, 'requires_resource': True, 'resource_type': 'Styling Station'}
            }
        )
        ServiceResourceRequirement.objects.update_or_create(
            service=hair_color,
            resource_type='Styling Station',
            defaults={'quantity': 1}
        )

        styling, _ = Service.objects.update_or_create(
            business=salon,
            slug='styling',
            defaults={
                'name': 'Event Blowout & Styling',
                'description': 'Voluminous blowout, curling, or flat iron glam styling for special events.',
                'duration_minutes': 30,
                'price': Decimal('45.00'),
                'buffer_time_minutes': 10,
                'capacity': 1,
                'color_hex': '#f59e0b',
                'booking_policies': {'requires_staff': True, 'requires_resource': True, 'resource_type': 'Styling Station'}
            }
        )
        ServiceResourceRequirement.objects.update_or_create(
            service=styling,
            resource_type='Styling Station',
            defaults={'quantity': 1}
        )

        # Salon Staff: Stylist A, Stylist B
        stylist_a, _ = Staff.objects.update_or_create(
            business=salon,
            name='Stylist A (Sarah Miller)',
            defaults={
                'email': 'sarah@demobeautystudio.com',
                'phone': '+1 (555) 890-1231',
                'title': 'Master Hair Stylist & Colorist',
                'bio': 'Specializing in dimensional balayage, precision cuts, and transformative color.',
                'color_hex': '#d97706',
                'is_active': True,
            }
        )
        stylist_a.assigned_services.set([haircut, hair_color, styling])

        stylist_b, _ = Staff.objects.update_or_create(
            business=salon,
            name='Stylist B (Samira Khan)',
            defaults={
                'email': 'samira@demobeautystudio.com',
                'phone': '+1 (555) 890-1232',
                'title': 'Senior Creative Stylist',
                'bio': 'Expert in texture, sleek blowouts, and editorial styling.',
                'color_hex': '#f59e0b',
                'is_active': True,
            }
        )
        stylist_b.assigned_services.set([haircut, styling])  # Qualified for Haircut and Styling

        for st in [stylist_a, stylist_b]:
            for d in range(1, 7):  # Tue-Sun
                StaffAvailability.objects.update_or_create(
                    staff=st,
                    day_of_week=d,
                    defaults={'start_time': datetime.time(9, 0), 'end_time': datetime.time(19, 0), 'is_active': True}
                )
                AvailabilityBreak.objects.update_or_create(
                    business=salon,
                    staff=st,
                    day_of_week=d,
                    defaults={'start_time': datetime.time(13, 0), 'end_time': datetime.time(14, 0), 'description': 'Stylist Midday Break'}
                )

        # Salon Resources: Styling Station 1, Styling Station 2
        station1, _ = Resource.objects.update_or_create(
            business=salon,
            name='Styling Station 1',
            defaults={'resource_type': 'Styling Station', 'capacity': 1, 'is_active': True}
        )
        station2, _ = Resource.objects.update_or_create(
            business=salon,
            name='Styling Station 2',
            defaults={'resource_type': 'Styling Station', 'capacity': 1, 'is_active': True}
        )

        # ---------------------------------------------------------
        # C. GYM: Demo Fitness Center
        # ---------------------------------------------------------
        gym, _ = Business.objects.get_or_create(
            slug='demo-fitness-center',
            defaults={
                'name': 'Demo Fitness Center',
                'business_type': gym_type,
                'tagline': 'Empower Your Strength, Movement & Health',
                'description': 'Premier fitness destination featuring group classes and elite personal training.',
                'time_zone': 'America/Los_Angeles',
                'contact_email': 'info@demofitnesscenter.com',
                'contact_phone': '+1 (555) 345-6789',
                'address': '720 Athletic Way, Los Angeles, CA',
                'status': 'active',
                'settings': {
                    'min_notice_hours': 1,
                    'max_advance_days': 21,
                    'slot_interval_minutes': 15,
                    'cancellation_deadline_hours': 6,
                    'confirmation_mode': 'auto',
                    'allow_client_staff_selection': True,
                }
            }
        )

        BusinessMember.objects.get_or_create(
            business=gym,
            user=admin_user,
            defaults={'role': 'owner'}
        )

        # Hours: Open 7 days a week, 06:00 - 21:00
        for day in range(7):
            BusinessHours.objects.update_or_create(
                business=gym,
                branch=None,
                day_of_week=day,
                defaults={'open_time': datetime.time(6, 0), 'close_time': datetime.time(21, 0), 'is_closed': False}
            )

        # Gym Services:
        # 1. Yoga Class (60 min, capacity=15) - Group Class
        # 2. Personal Training (45 min, capacity=1) - Exclusive 1:1
        yoga_class, _ = Service.objects.update_or_create(
            business=gym,
            slug='yoga-class',
            defaults={
                'name': 'Vinyasa Yoga Flow',
                'description': 'Dynamic flow connecting breath to movement, enhancing flexibility, strength and core balance.',
                'duration_minutes': 60,
                'price': Decimal('25.00'),
                'buffer_time_minutes': 15,
                'capacity': 15,  # Supports up to 15 clients per session!
                'color_hex': '#059669',
                'booking_policies': {'requires_staff': True, 'requires_resource': True, 'resource_type': 'Studio Room', 'is_group_session': True}
            }
        )
        ServiceResourceRequirement.objects.update_or_create(
            service=yoga_class,
            resource_type='Studio Room',
            defaults={'quantity': 1}
        )

        personal_training, _ = Service.objects.update_or_create(
            business=gym,
            slug='personal-training',
            defaults={
                'name': '1-on-1 Personal Training',
                'description': 'Individualized strength conditioning, form critique, and athletic programming.',
                'duration_minutes': 45,
                'price': Decimal('85.00'),
                'buffer_time_minutes': 15,
                'capacity': 1,  # Exclusive appointment!
                'color_hex': '#10b981',
                'booking_policies': {'requires_staff': True, 'requires_resource': True, 'resource_type': 'Training Room'}
            }
        )
        ServiceResourceRequirement.objects.update_or_create(
            service=personal_training,
            resource_type='Training Room',
            defaults={'quantity': 1}
        )

        # Gym Staff: Instructor A, Trainer B
        instructor_a, _ = Staff.objects.update_or_create(
            business=gym,
            name='Instructor A (Elena Rostova)',
            defaults={
                'email': 'elena@demofitnesscenter.com',
                'phone': '+1 (555) 345-6781',
                'title': 'Lead Yoga & Mindfulness Instructor',
                'bio': '500-hour certified yoga instructor passionate about alignment and mindful breathwork.',
                'color_hex': '#059669',
                'is_active': True,
            }
        )
        instructor_a.assigned_services.set([yoga_class])

        trainer_b, _ = Staff.objects.update_or_create(
            business=gym,
            name='Trainer B (Marcus Vance)',
            defaults={
                'email': 'marcus@demofitnesscenter.com',
                'phone': '+1 (555) 345-6782',
                'title': 'Certified Strength & Conditioning Specialist (CSCS)',
                'bio': 'Former collegiate athlete helping clients build functional strength and endurance.',
                'color_hex': '#10b981',
                'is_active': True,
            }
        )
        trainer_b.assigned_services.set([personal_training])

        for st in [instructor_a, trainer_b]:
            for d in range(7):
                StaffAvailability.objects.update_or_create(
                    staff=st,
                    day_of_week=d,
                    defaults={'start_time': datetime.time(7, 0), 'end_time': datetime.time(20, 0), 'is_active': True}
                )

        # Gym Resources: Studio Room (capacity 20), Training Room (capacity 2)
        studio_room, _ = Resource.objects.update_or_create(
            business=gym,
            name='Main Studio Room',
            defaults={'resource_type': 'Studio Room', 'capacity': 20, 'is_active': True}
        )
        training_room, _ = Resource.objects.update_or_create(
            business=gym,
            name='Private Training Room',
            defaults={'resource_type': 'Training Room', 'capacity': 2, 'is_active': True}
        )

        # Scheduled Class Occurrences for Gym (Upcoming days)
        now = timezone.now()
        for i in range(1, 8):
            session_date = (now + datetime.timedelta(days=i)).date()
            # 10:00 AM class
            start_dt = timezone.make_aware(datetime.datetime.combine(session_date, datetime.time(10, 0)))
            end_dt = start_dt + datetime.timedelta(minutes=60)
            ClassOccurrence.objects.get_or_create(
                business=gym,
                service=yoga_class,
                start_time=start_dt,
                defaults={
                    'instructor': instructor_a,
                    'resource': studio_room,
                    'end_time': end_dt,
                    'capacity': 15,
                    'booked_count': 0,
                    'status': 'scheduled',
                }
            )
            # 17:30 PM class
            start_dt_evening = timezone.make_aware(datetime.datetime.combine(session_date, datetime.time(17, 30)))
            end_dt_evening = start_dt_evening + datetime.timedelta(minutes=60)
            ClassOccurrence.objects.get_or_create(
                business=gym,
                service=yoga_class,
                start_time=start_dt_evening,
                defaults={
                    'instructor': instructor_a,
                    'resource': studio_room,
                    'end_time': end_dt_evening,
                    'capacity': 15,
                    'booked_count': 0,
                    'status': 'scheduled',
                }
            )

        # Seed Notification Templates for each business
        all_businesses = [clinic, salon, gym]
        events = [
            ('booking.created', 'Booking Request Received', 'Hello {{customer_name}}, your booking request for {{service_name}} on {{start_time}} at {{business_name}} has been received.'),
            ('booking.confirmed', 'Booking Confirmed - {{business_name}}', 'Dear {{customer_name}}, your appointment for {{service_name}} with {{staff_name}} is confirmed for {{start_time}}. Reference: {{reference}}. Manage or reschedule your booking at: {{manage_link}}'),
            ('booking.rescheduled', 'Appointment Rescheduled - {{business_name}}', 'Hello {{customer_name}}, your appointment for {{service_name}} has been rescheduled to {{start_time}}. Reference: {{reference}}'),
            ('booking.cancelled', 'Booking Cancellation Notice', 'Hi {{customer_name}}, your appointment for {{service_name}} on {{start_time}} has been cancelled. We look forward to welcoming you another time.'),
            ('appointment.reminder', 'Upcoming Appointment Reminder', 'Friendly reminder: You have an appointment tomorrow for {{service_name}} at {{start_time}} with {{business_name}}.'),
            ('daily.summary', 'Daily Appointments Summary', 'Good morning team. You have {{total_count}} appointments scheduled for today across all practitioners and resources.')
        ]

        for biz in all_businesses:
            for ev, subj, body in events:
                NotificationTemplate.objects.update_or_create(
                    business=biz,
                    event_type=ev,
                    channel='email',
                    defaults={'subject': subj, 'template_body': body, 'is_active': True}
                )
                NotificationTemplate.objects.update_or_create(
                    business=biz,
                    event_type=ev,
                    channel='whatsapp',
                    defaults={'subject': '', 'template_body': body, 'is_active': True}
                )

            # Mock Calendar Connection
            CalendarConnection.objects.get_or_create(
                business=biz,
                staff=None,
                calendar_provider='mock',
                defaults={
                    'calendar_id': f"{biz.slug}-calendar@mock.universalbooking.local",
                    'is_active': True,
                    'sync_settings': {'auto_sync': True, 'include_customer_details': True}
                }
            )

        # Sample Customers
        c1, _ = Customer.objects.get_or_create(
            business=clinic,
            email='john.doe@example.com',
            defaults={'name': 'John Doe', 'phone': '+1 (555) 111-2233'}
        )
        c2, _ = Customer.objects.get_or_create(
            business=salon,
            email='emma.watson@example.com',
            defaults={'name': 'Emma Watson', 'phone': '+1 (555) 444-5566'}
        )
        c3, _ = Customer.objects.get_or_create(
            business=gym,
            email='alex.runner@example.com',
            defaults={'name': 'Alex Runner', 'phone': '+1 (555) 777-8899'}
        )

        self.stdout.write(self.style.SUCCESS(
            "Successfully seeded demo configurations:\n"
            "  1. Clinic: Demo Health Clinic (General Consultation, Follow-up, Doctor A, Doctor B, Rooms 1 & 2)\n"
            "  2. Salon: Demo Beauty Studio (Haircut, Coloring, Styling, Stylist A, Stylist B, Stations 1 & 2)\n"
            "  3. Gym: Demo Fitness Center (Yoga Group Class [cap=15], 1-on-1 Personal Training, Studio & Training Room)\n"
            "  Admin user: 'admin' (password: 'admin12345')\n"
        ))
