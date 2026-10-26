import uuid
from django.db import models
from apps.businesses.models import Business
from apps.resources.models import Staff, Resource


class StaffAvailability(models.Model):
    """
    Standard weekly working schedule for a staff member.
    """
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    id = models.BigAutoField(primary_key=True)
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='working_hours')
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['day_of_week', 'start_time']
        verbose_name_plural = 'Staff Availabilities'

    def __str__(self):
        day_name = dict(self.DAY_CHOICES).get(self.day_of_week)
        return f"{self.staff.name} - {day_name}: {self.start_time} - {self.end_time}"


class AvailabilityBreak(models.Model):
    """
    Scheduled recurring breaks (e.g. Lunch break) during a shift.
    Can be assigned to an individual staff member or globally for the business.
    """
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    id = models.BigAutoField(primary_key=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='availability_breaks')
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, null=True, blank=True, related_name='breaks')
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    description = models.CharField(max_length=100, default='Lunch Break')

    class Meta:
        ordering = ['day_of_week', 'start_time']

    def __str__(self):
        target = self.staff.name if self.staff else f"{self.business.name} (Global)"
        day_name = dict(self.DAY_CHOICES).get(self.day_of_week)
        return f"Break: {target} on {day_name} {self.start_time}-{self.end_time}"


class AvailabilityException(models.Model):
    """
    Overrides standard schedules for specific dates/times:
    Public holidays, staff vacation/sick leave, or resource maintenance.
    Stored in UTC.
    """
    EXCEPTION_TYPES = [
        ('holiday', 'Public / Business Holiday'),
        ('leave', 'Staff Leave / Vacation'),
        ('maintenance', 'Resource Maintenance'),
        ('blackout', 'Custom Blackout Period'),
        ('special_hours', 'Special Working Hours'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='availability_exceptions')
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, null=True, blank=True, related_name='exceptions')
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, null=True, blank=True, related_name='exceptions')
    start_datetime = models.DateTimeField(db_index=True)
    end_datetime = models.DateTimeField(db_index=True)
    exception_type = models.CharField(max_length=30, choices=EXCEPTION_TYPES, default='holiday')
    is_available = models.BooleanField(
        default=False,
        help_text='If False, blocks bookings during this period. If True, grants availability during special hours.'
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_datetime']

    def __str__(self):
        target = self.staff.name if self.staff else (self.resource.name if self.resource else self.business.name)
        avail = "Open" if self.is_available else "Blocked"
        return f"[{self.exception_type.upper()}] {target} ({self.start_datetime} to {self.end_datetime}): {avail}"
