import uuid
import string
import random
from django.db import models
from django.contrib.auth.models import User
from apps.businesses.models import Business, Branch
from apps.services.models import Service
from apps.resources.models import Staff, Resource


def generate_booking_reference():
    """Generates a readable 8-character booking reference, e.g. BK-7X9K2M"""
    chars = string.ascii_uppercase + string.digits
    unique_part = ''.join(random.choices(chars, k=6))
    return f"BK-{unique_part}"


class Booking(models.Model):
    """
    Core booking model representing a reserved time slot for a customer.
    Stores all appointment timestamps in UTC.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Confirmation'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rescheduled', 'Rescheduled'),
        ('no_show', 'No Show'),
    ]

    SOURCE_CHOICES = [
        ('website', 'Public Website'),
        ('whatsapp', 'WhatsApp Bot'),
        ('admin', 'Admin Dashboard'),
        ('api', 'External API'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_reference = models.CharField(max_length=20, unique=True, default=generate_booking_reference, db_index=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='bookings')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, related_name='bookings')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='bookings')
    staff = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    assigned_resources = models.ManyToManyField(Resource, blank=True, related_name='bookings')
    
    # Stored in UTC!
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField(db_index=True)
    busy_end_time = models.DateTimeField(db_index=True, null=True, blank=True, help_text='End time including post-service buffer')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed', db_index=True)
    source_channel = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='website')
    notes = models.TextField(blank=True)
    
    # Idempotency support to prevent duplicate bookings
    idempotency_key = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    client_metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['business', 'start_time']),
            models.Index(fields=['business', 'status']),
            models.Index(fields=['staff', 'start_time', 'end_time']),
            models.Index(fields=['idempotency_key']),
        ]

    def __str__(self):
        staff_str = f" with {self.staff.name}" if self.staff else ""
        return f"{self.booking_reference}: {self.customer.name} - {self.service.name}{staff_str} ({self.start_time.strftime('%Y-%m-%d %H:%M')} UTC)"

    @property
    def is_active(self):
        return self.status in ('pending', 'confirmed')

    @property
    def duration_minutes(self):
        return int((self.end_time - self.start_time).total_seconds() / 60)


class BookingStatusHistory(models.Model):
    """
    Audit log of all status transitions for a booking.
    """
    id = models.BigAutoField(primary_key=True)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='status_history')
    previous_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    actor_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.booking.booking_reference}: {self.previous_status} -> {self.new_status} at {self.timestamp}"


class ClassOccurrence(models.Model):
    """
    Scheduled group session or class (e.g. Yoga Class at the Gym, Seminar, Group Consultation).
    Supports multiple participant bookings up to capacity.
    """
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('full', 'Full'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='class_occurrences')
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='class_occurrences')
    instructor = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name='taught_classes')
    resource = models.ForeignKey(Resource, on_delete=models.SET_NULL, null=True, blank=True, related_name='hosted_classes')
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField(db_index=True)
    capacity = models.PositiveIntegerField(help_text='Maximum participant capacity for this session')
    booked_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.service.name} on {self.start_time.strftime('%Y-%m-%d %H:%M')} ({self.booked_count}/{self.capacity} booked)"

    @property
    def remaining_spots(self):
        return max(0, self.capacity - self.booked_count)

    @property
    def is_available(self):
        return self.status == 'scheduled' and self.remaining_spots > 0


class ClassParticipant(models.Model):
    """
    Links a Customer and their Booking to a specific ClassOccurrence.
    """
    id = models.BigAutoField(primary_key=True)
    occurrence = models.ForeignKey(ClassOccurrence, on_delete=models.CASCADE, related_name='participants')
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='class_reservations')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, related_name='class_participations')
    reserved_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='confirmed')

    class Meta:
        unique_together = ('occurrence', 'customer')

    def __str__(self):
        return f"{self.customer.name} in {self.occurrence.service.name}"
