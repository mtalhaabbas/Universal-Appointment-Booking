import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify


class BusinessType(models.Model):
    """
    Categorizes the business vertical (e.g. Clinic, Salon, Gym, Consulting).
    Provides default policies and schema templates.
    """
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default='briefcase')
    default_settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Business(models.Model):
    """
    Primary tenant model. All core operations, resources, bookings,
    and configurations are isolated by Business.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('onboarding', 'Onboarding'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_type = models.ForeignKey(BusinessType, on_delete=models.PROTECT, related_name='businesses')
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    tagline = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    time_zone = models.CharField(max_length=64, default='UTC', help_text='IANA timezone string e.g. America/New_York')
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Configurable policies: buffer times, slot intervals, advance booking windows, auto-confirm
    settings = models.JSONField(
        default=dict,
        blank=True,
        help_text='Flexible business settings: min_notice_hours, max_advance_days, slot_interval_minutes, cancellation_deadline_hours, confirmation_mode'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Businesses'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        # Apply default fallback settings if empty
        defaults = {
            'min_notice_hours': 1,
            'max_advance_days': 60,
            'slot_interval_minutes': 15,
            'cancellation_deadline_hours': 24,
            'confirmation_mode': 'auto',  # 'auto' or 'manual'
            'allow_client_staff_selection': True,
        }
        for k, v in defaults.items():
            if k not in self.settings:
                self.settings[k] = v
        super().save(*args, **kwargs)


class Branch(models.Model):
    """
    Physical or virtual location belonging to a business.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    time_zone = models.CharField(max_length=64, blank=True, help_text='Overrides business timezone if different')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('business', 'slug')
        ordering = ['name']

    def __str__(self):
        return f"{self.business.name} - {self.name}"

    def effective_timezone(self):
        return self.time_zone or self.business.time_zone


class BusinessMember(models.Model):
    """
    User membership within a business tenant with RBAC.
    """
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('admin', 'Administrator'),
        ('staff', 'Staff Member'),
        ('receptionist', 'Receptionist'),
    ]

    id = models.BigAutoField(primary_key=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
    permissions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('business', 'user')

    def __str__(self):
        return f"{self.user.username} ({self.role}) at {self.business.name}"


class BusinessHours(models.Model):
    """
    Operating schedule per day of week (0=Monday, 6=Sunday).
    Can be assigned globally to business or scoped to a specific branch.
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
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='business_hours')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, null=True, blank=True, related_name='branch_hours')
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('business', 'branch', 'day_of_week')
        ordering = ['day_of_week', 'open_time']

    def __str__(self):
        branch_str = f" ({self.branch.name})" if self.branch else ""
        day_name = dict(self.DAY_CHOICES).get(self.day_of_week)
        if self.is_closed:
            return f"{self.business.name}{branch_str} - {day_name}: Closed"
        return f"{self.business.name}{branch_str} - {day_name}: {self.open_time} - {self.close_time}"


class AuditLog(models.Model):
    """
    Tracks actions, changes, and operations within a tenant for compliance and traceability.
    """
    id = models.BigAutoField(primary_key=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='audit_logs')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_actions')
    actor_name = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=100)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp}] {self.action} on {self.entity_type} {self.entity_id}"
