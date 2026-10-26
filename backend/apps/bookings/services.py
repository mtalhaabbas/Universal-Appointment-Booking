import uuid
import datetime
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.businesses.models import Business, AuditLog
from apps.services.models import Service
from apps.resources.models import Staff, Resource
from apps.customers.models import Customer
from apps.bookings.models import Booking, BookingStatusHistory, ClassOccurrence, ClassParticipant
from apps.availability.services import AvailabilityService
from apps.notifications.models import OutboxEvent


class BookingConflictError(ValidationError):
    """Raised when a timeslot is already booked or resources are occupied."""
    pass


class BookingPolicyError(ValidationError):
    """Raised when an action violates business policies (e.g. cancellation deadline)."""
    pass


class BookingService:
    """
    Centralized Booking Execution Engine.
    Handles booking creation, cancellation, rescheduling, and status transitions
    with strict concurrency control, database locks, and outbox event emission.
    """

    def __init__(self, business: Business):
        self.business = business
        try:
            self.tz = ZoneInfo(business.time_zone)
        except Exception:
            self.tz = ZoneInfo("UTC")

    @transaction.atomic
    def create_booking(
        self,
        service: Service,
        start_time: datetime.datetime,
        customer_data: dict,
        staff: Staff = None,
        occurrence_id: str = None,
        source_channel: str = 'website',
        notes: str = '',
        idempotency_key: str = None,
        actor=None
    ) -> tuple[Booking, bool]:
        """
        Creates a new booking with ACID guarantees and concurrency protection.
        Returns: (Booking, created_flag)
        """
        # 1. Idempotency verification
        if idempotency_key:
            existing_booking = Booking.objects.filter(
                business=self.business,
                idempotency_key=idempotency_key
            ).first()
            if existing_booking:
                return existing_booking, False

        # Ensure start_time is UTC
        if timezone.is_naive(start_time):
            start_time = timezone.make_aware(start_time, self.tz).astimezone(ZoneInfo("UTC"))
        else:
            start_time = start_time.astimezone(ZoneInfo("UTC"))

        # 2. Get or create Customer
        customer = self._resolve_customer(customer_data)

        # 3. Handle Group Class vs 1-on-1 Service
        if service.is_group_class or occurrence_id:
            return self._create_group_class_booking(
                service=service,
                occurrence_id=occurrence_id,
                start_time=start_time,
                customer=customer,
                source_channel=source_channel,
                notes=notes,
                idempotency_key=idempotency_key,
                actor=actor
            )

        # 4. Standard 1-on-1 Appointment: Calculate end time with buffer
        duration = service.duration_minutes
        total_duration = service.total_slot_duration
        end_time = start_time + datetime.timedelta(minutes=duration)
        busy_end_time = start_time + datetime.timedelta(minutes=total_duration)

        # 5. Lock and select qualified staff
        assigned_staff = self._resolve_and_lock_staff(service, staff, start_time, busy_end_time)

        # 6. Lock and allocate required resources
        assigned_resources = self._resolve_and_lock_resources(service, start_time, busy_end_time)

        # 7. Check confirmation policy (auto vs manual)
        default_status = 'confirmed' if self.business.settings.get('confirmation_mode', 'auto') == 'auto' else 'pending'

        # 8. Create Booking
        booking = Booking.objects.create(
            business=self.business,
            customer=customer,
            service=service,
            staff=assigned_staff,
            start_time=start_time,
            end_time=end_time,
            busy_end_time=busy_end_time,
            status=default_status,
            source_channel=source_channel,
            notes=notes,
            idempotency_key=idempotency_key,
            client_metadata={'busy_end_time': busy_end_time.isoformat()}
        )

        if assigned_resources:
            booking.assigned_resources.set(assigned_resources)

        # 9. Record Status History
        BookingStatusHistory.objects.create(
            booking=booking,
            previous_status='',
            new_status=default_status,
            actor=actor,
            actor_name=actor.username if actor else f"System ({source_channel})",
            notes=f"Booking created via {source_channel}"
        )

        # 10. Emit Transactional Outbox Event
        event_name = 'booking.confirmed' if default_status == 'confirmed' else 'booking.created'
        self._emit_outbox_event(event_name, booking)

        # 11. Audit Log
        AuditLog.objects.create(
            business=self.business,
            actor=actor,
            actor_name=actor.username if actor else source_channel,
            action='booking.create',
            entity_type='Booking',
            entity_id=str(booking.id),
            metadata={'reference': booking.booking_reference, 'service': service.name, 'start_time': start_time.isoformat()}
        )

        return booking, True

    def _create_group_class_booking(self, service, occurrence_id, start_time, customer, source_channel, notes, idempotency_key, actor):
        """Creates a booking for a shared group class (e.g. Yoga Class) with row lock on occurrence"""
        occ_query = ClassOccurrence.objects.select_for_update()
        if occurrence_id:
            occurrence = occ_query.filter(id=occurrence_id, business=self.business).first()
        else:
            occurrence = occ_query.filter(service=service, business=self.business, start_time=start_time).first()

        if not occurrence:
            raise BookingConflictError("Selected group class session does not exist.")

        if occurrence.booked_count >= occurrence.capacity:
            raise BookingConflictError(f"Session is fully booked ({occurrence.capacity}/{occurrence.capacity} participants).")

        # Check if customer is already enrolled
        if ClassParticipant.objects.filter(occurrence=occurrence, customer=customer, status='confirmed').exists():
            raise BookingConflictError("Customer is already enrolled in this class session.")

        # Create Booking
        booking = Booking.objects.create(
            business=self.business,
            customer=customer,
            service=service,
            staff=occurrence.instructor,
            start_time=occurrence.start_time,
            end_time=occurrence.end_time,
            status='confirmed',
            source_channel=source_channel,
            notes=notes,
            idempotency_key=idempotency_key,
        )
        if occurrence.resource:
            booking.assigned_resources.add(occurrence.resource)

        # Increment booked count atomically
        occurrence.booked_count += 1
        if occurrence.booked_count >= occurrence.capacity:
            occurrence.status = 'full'
        occurrence.save(update_fields=['booked_count', 'status'])

        # Create Participant record
        ClassParticipant.objects.create(
            occurrence=occurrence,
            booking=booking,
            customer=customer,
            status='confirmed'
        )

        # Status History
        BookingStatusHistory.objects.create(
            booking=booking,
            previous_status='',
            new_status='confirmed',
            actor=actor,
            actor_name=actor.username if actor else f"System ({source_channel})",
            notes="Enrolled into group class occurrence"
        )

        # Outbox Event
        self._emit_outbox_event('booking.confirmed', booking)

        return booking, True

    def _resolve_customer(self, customer_data: dict) -> Customer:
        email = customer_data.get('email', '').strip().lower()
        name = customer_data.get('name', '').strip()
        phone = customer_data.get('phone', '').strip()

        if not name:
            raise ValidationError("Customer name is required.")

        if email:
            customer, _ = Customer.objects.get_or_create(
                business=self.business,
                email=email,
                defaults={'name': name, 'phone': phone}
            )
            if phone and not customer.phone:
                customer.phone = phone
                customer.save(update_fields=['phone'])
            return customer
        else:
            # Fallback customer if no email
            customer = Customer.objects.filter(business=self.business, phone=phone).first() if phone else None
            if not customer:
                customer = Customer.objects.create(
                    business=self.business,
                    name=name,
                    phone=phone,
                    email=f"client_{uuid.uuid4().hex[:8]}@guest.local"
                )
            return customer

    def _resolve_and_lock_staff(self, service: Service, requested_staff: Staff, start_time: datetime.datetime, busy_end_time: datetime.datetime) -> Staff:
        requires_staff = service.booking_policies.get('requires_staff', True)
        if not requires_staff:
            return None

        # Lock active staff rows with select_for_update
        staff_qs = Staff.objects.select_for_update().filter(business=self.business, is_active=True)

        if requested_staff:
            candidate_staff = list(staff_qs.filter(id=requested_staff.id))
        else:
            # Qualified staff
            qualified = staff_qs.filter(assigned_services=service)
            candidate_staff = list(qualified if qualified.exists() else staff_qs)

        if not candidate_staff:
            raise BookingConflictError("No active staff member available for this service.")

        # Find first available staff without overlapping active bookings
        for s in candidate_staff:
            has_overlap = Booking.objects.filter(
                business=self.business,
                staff=s,
                status__in=['pending', 'confirmed']
            ).filter(
                Q(busy_end_time__isnull=False, start_time__lt=busy_end_time, busy_end_time__gt=start_time) |
                Q(busy_end_time__isnull=True, start_time__lt=busy_end_time, end_time__gt=start_time)
            ).exists()

            if not has_overlap:
                return s

        staff_name = requested_staff.name if requested_staff else "Selected staff"
        raise BookingConflictError(f"{staff_name} is no longer available at this time.")

    def _resolve_and_lock_resources(self, service: Service, start_time: datetime.datetime, busy_end_time: datetime.datetime) -> list[Resource]:
        requirements = list(service.resource_requirements.all())
        if not requirements:
            return []

        allocated_resources = []
        for req in requirements:
            # Lock resources with select_for_update
            candidates = list(Resource.objects.select_for_update().filter(
                business=self.business,
                resource_type__iexact=req.resource_type,
                is_active=True
            ))

            free_candidates = []
            for res in candidates:
                overlapping_count = Booking.objects.filter(
                    business=self.business,
                    assigned_resources=res,
                    status__in=['pending', 'confirmed']
                ).filter(
                    Q(busy_end_time__isnull=False, start_time__lt=busy_end_time, busy_end_time__gt=start_time) |
                    Q(busy_end_time__isnull=True, start_time__lt=busy_end_time, end_time__gt=start_time)
                ).count()

                if overlapping_count < res.capacity:
                    free_candidates.append(res)

            if len(free_candidates) < req.quantity:
                raise BookingConflictError(f"No available {req.resource_type} for this time slot.")

            allocated_resources.extend(free_candidates[:req.quantity])

        return allocated_resources

    @transaction.atomic
    def cancel_booking(self, booking: Booking, reason: str = '', actor=None, bypass_policy: bool = False) -> Booking:
        """
        Cancels an active booking and releases staff, resources, or group class spot.
        """
        if booking.status == 'cancelled':
            return booking

        # Check cancellation policy
        if not bypass_policy:
            now_utc = timezone.now()
            hours_until_start = (booking.start_time - now_utc).total_seconds() / 3600
            cancellation_deadline = self.business.settings.get('cancellation_deadline_hours', 24)

            if hours_until_start < cancellation_deadline:
                raise BookingPolicyError(
                    f"Cancellations must be made at least {cancellation_deadline} hours before the appointment. "
                    f"Only {int(hours_until_start)} hours remain."
                )

        prev_status = booking.status
        booking.status = 'cancelled'
        booking.notes = f"{booking.notes}\n[Cancelled]: {reason}".strip()
        booking.save(update_fields=['status', 'notes', 'updated_at'])

        # If group class: decrement booked count
        part = ClassParticipant.objects.filter(booking=booking).first()
        if part:
            part.status = 'cancelled'
            part.save(update_fields=['status'])
            occ = part.occurrence
            if occ.booked_count > 0:
                occ.booked_count -= 1
                if occ.status == 'full':
                    occ.status = 'scheduled'
                occ.save(update_fields=['booked_count', 'status'])

        # Record Status History
        BookingStatusHistory.objects.create(
            booking=booking,
            previous_status=prev_status,
            new_status='cancelled',
            actor=actor,
            actor_name=actor.username if actor else 'Client',
            notes=reason or 'Booking cancelled by user request'
        )

        # Emit Outbox Event
        self._emit_outbox_event('booking.cancelled', booking)

        # Audit Log
        AuditLog.objects.create(
            business=self.business,
            actor=actor,
            actor_name=actor.username if actor else 'Client',
            action='booking.cancel',
            entity_type='Booking',
            entity_id=str(booking.id),
            metadata={'reference': booking.booking_reference, 'reason': reason}
        )

        return booking

    @transaction.atomic
    def reschedule_booking(self, booking: Booking, new_start_time: datetime.datetime, actor=None, bypass_policy: bool = False) -> Booking:
        """
        Reschedules an existing booking to a new available time slot.
        """
        if booking.status == 'cancelled':
            raise BookingPolicyError("Cannot reschedule a cancelled booking.")

        if timezone.is_naive(new_start_time):
            new_start_time = timezone.make_aware(new_start_time, self.tz).astimezone(ZoneInfo("UTC"))
        else:
            new_start_time = new_start_time.astimezone(ZoneInfo("UTC"))

        duration = booking.service.duration_minutes
        total_duration = booking.service.total_slot_duration
        new_end_time = new_start_time + datetime.timedelta(minutes=duration)
        busy_end_time = new_start_time + datetime.timedelta(minutes=total_duration)

        # Check staff availability for new slot (excluding current booking)
        if booking.staff:
            has_overlap = Booking.objects.filter(
                business=self.business,
                staff=booking.staff,
                status__in=['pending', 'confirmed']
            ).exclude(id=booking.id).filter(
                Q(busy_end_time__isnull=False, start_time__lt=busy_end_time, busy_end_time__gt=new_start_time) |
                Q(busy_end_time__isnull=True, start_time__lt=busy_end_time, end_time__gt=new_start_time)
            ).exists()

            if has_overlap:
                raise BookingConflictError(f"{booking.staff.name} is not available at the requested new time.")

        # Check resource availability for new slot
        for res in booking.assigned_resources.all():
            overlap_count = Booking.objects.filter(
                business=self.business,
                assigned_resources=res,
                status__in=['pending', 'confirmed']
            ).exclude(id=booking.id).filter(
                Q(busy_end_time__isnull=False, start_time__lt=busy_end_time, busy_end_time__gt=new_start_time) |
                Q(busy_end_time__isnull=True, start_time__lt=busy_end_time, end_time__gt=new_start_time)
            ).count()

            if overlap_count >= res.capacity:
                raise BookingConflictError(f"{res.name} is not available at the requested new time.")

        prev_start = booking.start_time
        prev_status = booking.status

        booking.start_time = new_start_time
        booking.end_time = new_end_time
        booking.busy_end_time = busy_end_time
        booking.status = 'confirmed'
        booking.save(update_fields=['start_time', 'end_time', 'busy_end_time', 'status', 'updated_at'])

        # Status History
        BookingStatusHistory.objects.create(
            booking=booking,
            previous_status=prev_status,
            new_status='rescheduled',
            actor=actor,
            actor_name=actor.username if actor else 'Client',
            notes=f"Rescheduled from {prev_start.isoformat()} to {new_start_time.isoformat()}"
        )

        # Emit Outbox Event
        self._emit_outbox_event('booking.rescheduled', booking)

        # Audit Log
        AuditLog.objects.create(
            business=self.business,
            actor=actor,
            actor_name=actor.username if actor else 'Client',
            action='booking.reschedule',
            entity_type='Booking',
            entity_id=str(booking.id),
            metadata={'reference': booking.booking_reference, 'new_start_time': new_start_time.isoformat()}
        )

        return booking

    def _emit_outbox_event(self, event_type: str, booking: Booking):
        """Emits an outbox event matching standardized n8n payload specification"""
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "business_id": str(self.business.id),
            "business_slug": self.business.slug,
            "business_name": self.business.name,
            "booking_id": str(booking.id),
            "booking_reference": booking.booking_reference,
            "service_id": str(booking.service.id),
            "service_name": booking.service.name,
            "staff_id": str(booking.staff.id) if booking.staff else None,
            "staff_name": booking.staff.name if booking.staff else "Unassigned",
            "customer_name": booking.customer.name,
            "customer_email": booking.customer.email,
            "customer_phone": booking.customer.phone,
            "starts_at": booking.start_time.isoformat(),
            "ends_at": booking.end_time.isoformat(),
            "status": booking.status,
            "timezone": self.business.time_zone,
            "notification_channels": ["email", "whatsapp"],
            "timestamp": timezone.now().isoformat(),
        }

        OutboxEvent.objects.create(
            event_id=event_id,
            business=self.business,
            event_type=event_type,
            payload=payload,
            status='pending'
        )
