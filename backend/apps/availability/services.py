import datetime
from zoneinfo import ZoneInfo
from django.utils import timezone
from django.db.models import Q

from apps.businesses.models import Business, BusinessHours
from apps.services.models import Service, ServiceResourceRequirement
from apps.resources.models import Staff, Resource
from apps.availability.models import StaffAvailability, AvailabilityBreak, AvailabilityException
from apps.bookings.models import Booking, ClassOccurrence


class AvailabilityService:
    """
    Centralized, policy-driven scheduling engine.
    Calculates available time slots across all business verticals
    (clinics, salons, gyms, etc.) without vertical-specific hardcoding.
    """

    def __init__(self, business: Business):
        self.business = business
        try:
            self.tz = ZoneInfo(business.time_zone)
        except Exception:
            self.tz = ZoneInfo("UTC")

    def get_available_slots(
        self,
        service: Service,
        target_date: datetime.date,
        staff: Staff = None,
        branch=None
    ) -> list[dict]:
        """
        Calculates all bookable time slots on target_date for a given service.
        Returns a list of dicts:
        [
            {
                "start_time": "2026-11-02T10:00:00Z",
                "end_time": "2026-11-02T10:30:00Z",
                "local_start_time": "10:00",
                "local_end_time": "10:30",
                "formatted_time": "10:00 AM - 10:30 AM",
                "available_staff": [{"id": "...", "name": "..."}],
                "available_resources": [{"id": "...", "name": "..."}],
                "is_group_class": False,
                "remaining_capacity": 1
            }, ...
        ]
        """
        # If the service is a scheduled group class (e.g. Yoga Class at Gym),
        # return scheduled ClassOccurrences for target_date!
        if service.is_group_class:
            return self._get_group_class_slots(service, target_date, staff, branch)

        # 1. Check advance booking window and minimum notice
        now_utc = timezone.now()
        now_local = now_utc.astimezone(self.tz)

        min_notice_hours = self.business.settings.get('min_notice_hours', 1)
        max_advance_days = self.business.settings.get('max_advance_days', 60)
        earliest_allowed_local = now_local + datetime.timedelta(hours=min_notice_hours)
        latest_allowed_date = (now_local + datetime.timedelta(days=max_advance_days)).date()

        if target_date < now_local.date() or target_date > latest_allowed_date:
            return []

        # 2. Check Business/Branch Operating Hours for the day of week
        weekday = target_date.weekday()  # 0=Monday, 6=Sunday
        hours_qs = BusinessHours.objects.filter(business=self.business, day_of_week=weekday)
        if branch:
            branch_hours = hours_qs.filter(branch=branch).first()
            operating_hours = branch_hours if branch_hours else hours_qs.filter(branch__isnull=True).first()
        else:
            operating_hours = hours_qs.filter(branch__isnull=True).first()

        if not operating_hours or operating_hours.is_closed or not operating_hours.open_time or not operating_hours.close_time:
            return []

        # 3. Check Business-wide Holiday / Blackout Exceptions for this day
        day_start_local = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=self.tz)
        day_end_local = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=self.tz)
        day_start_utc = day_start_local.astimezone(ZoneInfo("UTC"))
        day_end_utc = day_end_local.astimezone(ZoneInfo("UTC"))

        business_blocked = AvailabilityException.objects.filter(
            business=self.business,
            staff__isnull=True,
            resource__isnull=True,
            is_available=False,
            start_datetime__lt=day_end_utc,
            end_datetime__gt=day_start_utc
        ).exists()

        if business_blocked:
            return []

        # 4. Identify candidate staff members qualified for this service
        requires_staff = service.booking_policies.get('requires_staff', True)
        if staff:
            if not staff.is_active or not staff.assigned_services.filter(id=service.id).exists():
                return []
            candidate_staff = [staff]
        elif requires_staff:
            candidate_staff = list(service.qualified_staff.filter(is_active=True))
            if not candidate_staff:
                # If no staff assigned specifically, check if any active staff belongs to the business
                candidate_staff = list(Staff.objects.filter(business=self.business, is_active=True))
        else:
            candidate_staff = [None]

        # 5. Identify required resources
        requirements = list(service.resource_requirements.all())
        requires_resource = bool(requirements)

        # 6. Fetch existing bookings on target date
        existing_bookings = list(Booking.objects.filter(
            business=self.business,
            status__in=['pending', 'confirmed'],
            start_time__lt=day_end_utc,
            end_time__gt=day_start_utc
        ).prefetch_related('assigned_resources'))

        # Fetch staff exceptions
        staff_exceptions = list(AvailabilityException.objects.filter(
            business=self.business,
            staff__in=[s for s in candidate_staff if s is not None],
            start_datetime__lt=day_end_utc,
            end_datetime__gt=day_start_utc
        ))

        # Fetch resource exceptions
        resource_exceptions = list(AvailabilityException.objects.filter(
            business=self.business,
            resource__isnull=False,
            start_datetime__lt=day_end_utc,
            end_datetime__gt=day_start_utc
        ))

        # 7. Slot generation parameters
        slot_interval = self.business.settings.get('slot_interval_minutes', 15)
        service_duration = service.duration_minutes
        buffer_time = service.buffer_time_minutes
        total_duration = service.total_slot_duration

        # Time range for candidate slots
        current_time_dt = datetime.datetime.combine(target_date, operating_hours.open_time, tzinfo=self.tz)
        close_time_dt = datetime.datetime.combine(target_date, operating_hours.close_time, tzinfo=self.tz)

        available_slots = []

        while current_time_dt + datetime.timedelta(minutes=service_duration) <= close_time_dt:
            slot_start_local = current_time_dt
            slot_end_local = slot_start_local + datetime.timedelta(minutes=service_duration)
            slot_busy_end_local = slot_start_local + datetime.timedelta(minutes=total_duration)

            # Check lead notice
            if slot_start_local < earliest_allowed_local:
                current_time_dt += datetime.timedelta(minutes=slot_interval)
                continue

            slot_start_utc = slot_start_local.astimezone(ZoneInfo("UTC"))
            slot_end_utc = slot_end_local.astimezone(ZoneInfo("UTC"))
            slot_busy_end_utc = slot_busy_end_local.astimezone(ZoneInfo("UTC"))

            # Find matching staff available for this slot
            valid_staff_for_slot = []
            for s in candidate_staff:
                if s is None:
                    valid_staff_for_slot.append(None)
                    continue

                if self._is_staff_available(s, weekday, slot_start_local, slot_busy_end_local, slot_start_utc, slot_busy_end_utc, staff_exceptions, existing_bookings):
                    valid_staff_for_slot.append(s)

            if requires_staff and not valid_staff_for_slot:
                current_time_dt += datetime.timedelta(minutes=slot_interval)
                continue

            # Find matching resources available for this slot
            valid_resources = []
            if requires_resource:
                has_resources, allocated_resources = self._check_resource_availability(
                    requirements, slot_start_utc, slot_busy_end_utc, resource_exceptions, existing_bookings, branch
                )
                if not has_resources:
                    current_time_dt += datetime.timedelta(minutes=slot_interval)
                    continue
                valid_resources = allocated_resources

            # If we reached here, the slot is available!
            available_slots.append({
                "start_time": slot_start_utc.isoformat(),
                "end_time": slot_end_utc.isoformat(),
                "busy_end_time": slot_busy_end_utc.isoformat(),
                "local_start_time": slot_start_local.strftime("%H:%M"),
                "local_end_time": slot_end_local.strftime("%H:%M"),
                "formatted_time": f"{slot_start_local.strftime('%I:%M %p')} - {slot_end_local.strftime('%I:%M %p')}".lstrip("0"),
                "available_staff": [{"id": str(s.id), "name": s.name, "title": s.title} for s in valid_staff_for_slot if s is not None],
                "available_resources": [{"id": str(r.id), "name": r.name, "resource_type": r.resource_type} for r in valid_resources],
                "is_group_class": False,
                "remaining_capacity": 1,
            })

            current_time_dt += datetime.timedelta(minutes=slot_interval)

        return available_slots

    def _is_staff_available(self, staff, weekday, slot_start_local, slot_busy_end_local, slot_start_utc, slot_busy_end_utc, staff_exceptions, existing_bookings):
        # A. Working hours for this day of week
        shift = StaffAvailability.objects.filter(staff=staff, day_of_week=weekday, is_active=True).first()
        if not shift:
            return False

        if slot_start_local.time() < shift.start_time or slot_busy_end_local.time() > shift.end_time:
            return False

        # B. Scheduled breaks (e.g. Lunch)
        breaks = AvailabilityBreak.objects.filter(
            Q(staff=staff) | Q(business=self.business, staff__isnull=True),
            day_of_week=weekday
        )
        for b in breaks:
            # Overlap test: slot_start < break_end and slot_busy_end > break_start
            if slot_start_local.time() < b.end_time and slot_busy_end_local.time() > b.start_time:
                return False

        # C. Exceptions / Leave
        for exc in staff_exceptions:
            if exc.staff_id == staff.id and not exc.is_available:
                if slot_start_utc < exc.end_datetime and slot_busy_end_utc > exc.start_datetime:
                    return False

        # D. Existing bookings for this staff member
        for bkg in existing_bookings:
            if bkg.staff_id == staff.id:
                bkg_busy_end = bkg.busy_end_time or bkg.end_time
                if slot_start_utc < bkg_busy_end and slot_busy_end_utc > bkg.start_time:
                    return False

        return True

    def _check_resource_availability(self, requirements, slot_start_utc, slot_busy_end_utc, resource_exceptions, existing_bookings, branch):
        allocated = []

        for req in requirements:
            # Candidate resources matching resource_type
            res_qs = Resource.objects.filter(
                business=self.business,
                resource_type__iexact=req.resource_type,
                is_active=True
            )
            if branch:
                res_qs = res_qs.filter(Q(branch=branch) | Q(branch__isnull=True))

            candidates = list(res_qs)
            free_candidates = []

            for res in candidates:
                # Check exceptions for this resource
                blocked = False
                for exc in resource_exceptions:
                    if exc.resource_id == res.id and not exc.is_available:
                        if slot_start_utc < exc.end_datetime and slot_busy_end_utc > exc.start_datetime:
                            blocked = True
                            break
                if blocked:
                    continue

                # Check existing bookings using this resource
                overlapping_count = 0
                for bkg in existing_bookings:
                    if any(r.id == res.id for r in bkg.assigned_resources.all()):
                        bkg_busy_end = bkg.busy_end_time or bkg.end_time
                        if slot_start_utc < bkg_busy_end and slot_busy_end_utc > bkg.start_time:
                            overlapping_count += 1

                if overlapping_count < res.capacity:
                    free_candidates.append(res)

            if len(free_candidates) < req.quantity:
                return False, []

            allocated.extend(free_candidates[:req.quantity])

        return True, allocated

    def _get_group_class_slots(self, service: Service, target_date: datetime.date, staff: Staff = None, branch=None):
        """
        Retrieves scheduled group sessions (ClassOccurrence) for group services (e.g. Gym Yoga).
        """
        day_start_local = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=self.tz)
        day_end_local = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=self.tz)
        day_start_utc = day_start_local.astimezone(ZoneInfo("UTC"))
        day_end_utc = day_end_local.astimezone(ZoneInfo("UTC"))

        occurrences = ClassOccurrence.objects.filter(
            business=self.business,
            service=service,
            status='scheduled',
            start_time__gte=day_start_utc,
            start_time__lte=day_end_utc
        ).select_related('instructor', 'resource')

        if staff:
            occurrences = occurrences.filter(instructor=staff)

        slots = []
        now_utc = timezone.now()

        for occ in occurrences:
            if occ.start_time <= now_utc or occ.remaining_spots <= 0:
                continue

            occ_start_local = occ.start_time.astimezone(self.tz)
            occ_end_local = occ.end_time.astimezone(self.tz)

            slots.append({
                "occurrence_id": str(occ.id),
                "start_time": occ.start_time.isoformat(),
                "end_time": occ.end_time.isoformat(),
                "local_start_time": occ_start_local.strftime("%H:%M"),
                "local_end_time": occ_end_local.strftime("%H:%M"),
                "formatted_time": f"{occ_start_local.strftime('%I:%M %p')} - {occ_end_local.strftime('%I:%M %p')}".lstrip("0"),
                "available_staff": [{"id": str(occ.instructor.id), "name": occ.instructor.name, "title": occ.instructor.title}] if occ.instructor else [],
                "available_resources": [{"id": str(occ.resource.id), "name": occ.resource.name, "resource_type": occ.resource.resource_type}] if occ.resource else [],
                "is_group_class": True,
                "capacity": occ.capacity,
                "booked_count": occ.booked_count,
                "remaining_capacity": occ.remaining_spots,
            })

        return slots
