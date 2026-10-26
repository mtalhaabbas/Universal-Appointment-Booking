import uuid
from django.db import models
from apps.businesses.models import Business
from apps.resources.models import Staff
from apps.bookings.models import Booking


class CalendarConnection(models.Model):
    """
    OAuth and sync connection metadata for external calendar providers.
    Supports Google Calendar and a fully documented Mock Calendar for testing.
    """
    PROVIDER_CHOICES = [
        ('google', 'Google Calendar'),
        ('mock', 'Mock Calendar Provider (Testing/Demo)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='calendar_connections')
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, null=True, blank=True, related_name='calendar_connections')
    calendar_provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, default='mock')
    calendar_id = models.CharField(max_length=255, default='primary', help_text='External calendar identifier')
    
    # Secure token storage
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    sync_settings = models.JSONField(default=dict, blank=True)
    
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        owner = self.staff.name if self.staff else self.business.name
        return f"{self.get_calendar_provider_display()} for {owner}"


class CalendarEventMapping(models.Model):
    """
    Maps an internal Booking to an external Calendar Event ID to keep them in sync.
    """
    SYNC_STATES = [
        ('synced', 'Synced'),
        ('pending_create', 'Pending Creation'),
        ('pending_update', 'Pending Update'),
        ('pending_delete', 'Pending Deletion'),
        ('failed', 'Sync Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='calendar_mappings')
    calendar_connection = models.ForeignKey(CalendarConnection, on_delete=models.CASCADE, related_name='event_mappings')
    external_event_id = models.CharField(max_length=255, db_index=True)
    sync_state = models.CharField(max_length=30, choices=SYNC_STATES, default='synced')
    last_synced_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True)

    class Meta:
        unique_together = ('booking', 'calendar_connection')

    def __str__(self):
        return f"Event {self.external_event_id} <=> Booking {self.booking.booking_reference} ({self.sync_state})"


class WebhookLog(models.Model):
    """
    Stores inbound webhooks (e.g. from WhatsApp Cloud API or external systems)
    for idempotency verification and audit trails.
    """
    STATUS_CHOICES = [
        ('received', 'Received'),
        ('processed', 'Processed'),
        ('ignored', 'Ignored'),
        ('failed', 'Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    external_event_id = models.CharField(max_length=128, db_index=True, blank=True)
    provider = models.CharField(max_length=50, default='whatsapp')
    processing_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='received')
    payload = models.JSONField(default=dict)
    response_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.provider}] {self.external_event_id or 'No ID'} - {self.processing_status}"
