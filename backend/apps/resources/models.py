import uuid
from django.db import models
from django.contrib.auth.models import User
from apps.businesses.models import Business, Branch
from apps.services.models import Service


class Staff(models.Model):
    """
    Staff members, practitioners, doctors, stylists, or instructors
    who perform services.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='staff_members')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_members')
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_profile')
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    title = models.CharField(max_length=100, blank=True, help_text='Role/Title e.g. Doctor, Stylist, Trainer')
    bio = models.TextField(blank=True)
    assigned_services = models.ManyToManyField(Service, blank=True, related_name='qualified_staff')
    color_hex = models.CharField(max_length=10, default='#0d9488')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Staff'

    def __str__(self):
        return f"{self.name} ({self.title or 'Staff'}) - {self.business.name}"


class Resource(models.Model):
    """
    Physical rooms, stations, chairs, equipment required for services.
    E.g. Consultation Room, Styling Station, Studio Room.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='resources')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='resources')
    name = models.CharField(max_length=150)
    resource_type = models.CharField(
        max_length=100,
        help_text='Resource category matching service requirements e.g. Consultation Room, Styling Station, Studio Room'
    )
    capacity = models.PositiveIntegerField(
        default=1,
        help_text='Simultaneous occupancy capacity (e.g. 1 for exclusive room/station, 20 for large studio)'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['resource_type', 'name']

    def __str__(self):
        return f"{self.name} [{self.resource_type}] - {self.business.name}"
