import uuid
from decimal import Decimal
from django.db import models
from django.utils.text import slugify
from apps.businesses.models import Business


class Service(models.Model):
    """
    Defines a bookable service offered by a business.
    Supports 1:1 appointments (capacity=1) or group sessions (capacity>1).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='services')
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(help_text='Duration of service in minutes')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    buffer_time_minutes = models.PositiveIntegerField(
        default=0,
        help_text='Post-service cleanup / turnaround buffer in minutes'
    )
    capacity = models.PositiveIntegerField(
        default=1,
        help_text='Maximum concurrent clients (1 for 1-on-1 consultations/haircuts, >1 for group classes)'
    )
    color_hex = models.CharField(max_length=10, default='#2563eb')
    
    # Configurable policies:
    # requires_staff: bool
    # requires_resource: bool
    # resource_type: string (e.g., 'Consultation Room', 'Styling Station', 'Studio Room')
    # min_cancel_hours: int
    # is_group_session: bool
    booking_policies = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('business', 'slug')
        ordering = ['name']

    def __str__(self):
        return f"{self.business.name} - {self.name} ({self.duration_minutes}m)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        # Populate default booking policies
        if 'requires_staff' not in self.booking_policies:
            self.booking_policies['requires_staff'] = True
        if 'allow_client_select_staff' not in self.booking_policies:
            self.booking_policies['allow_client_select_staff'] = True
        super().save(*args, **kwargs)

    @property
    def total_slot_duration(self):
        """Total duration including buffer time"""
        return self.duration_minutes + self.buffer_time_minutes

    @property
    def is_group_class(self):
        return self.capacity > 1


class ServiceResourceRequirement(models.Model):
    """
    Specifies which resources and quantities are required to perform a service.
    E.g. Clinic General Consultation requires 1 'Consultation Room'.
    Salon Haircut requires 1 'Styling Station'.
    Gym Yoga Class requires 1 'Studio Room'.
    """
    id = models.BigAutoField(primary_key=True)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='resource_requirements')
    resource_type = models.CharField(
        max_length=100,
        help_text='The type of resource required (e.g. Consultation Room, Styling Station, Studio Room)'
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('service', 'resource_type')

    def __str__(self):
        return f"{self.service.name} requires {self.quantity}x {self.resource_type}"
