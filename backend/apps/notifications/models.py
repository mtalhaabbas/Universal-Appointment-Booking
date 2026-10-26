import uuid
from django.db import models
from apps.businesses.models import Business
from apps.bookings.models import Booking


class NotificationTemplate(models.Model):
    """
    Configurable message templates per business, event type, and channel.
    Placeholders: {{customer_name}}, {{service_name}}, {{staff_name}},
    {{business_name}}, {{start_time}}, {{end_time}}, {{reference}}, {{manage_link}}
    """
    EVENT_CHOICES = [
        ('booking.created', 'Booking Created'),
        ('booking.confirmed', 'Booking Confirmed'),
        ('booking.rescheduled', 'Booking Rescheduled'),
        ('booking.cancelled', 'Booking Cancelled'),
        ('appointment.reminder', 'Appointment Reminder Due'),
        ('daily.summary', 'Daily Booking Summary'),
    ]

    CHANNEL_CHOICES = [
        ('email', 'Email'),
        ('whatsapp', 'WhatsApp'),
        ('webhook', 'Webhook / n8n'),
    ]

    id = models.BigAutoField(primary_key=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='notification_templates')
    event_type = models.CharField(max_length=50, choices=EVENT_CHOICES)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    subject = models.CharField(max_length=255, blank=True, help_text='Email subject or message title')
    template_body = models.TextField(help_text='Template body with {{variables}}')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('business', 'event_type', 'channel')
        ordering = ['event_type', 'channel']

    def __str__(self):
        return f"{self.business.name} - {self.event_type} ({self.channel})"


class NotificationDelivery(models.Model):
    """
    Log of sent notifications and delivery statuses with retry history.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent / Delivered'),
        ('failed', 'Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='notification_deliveries')
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')
    event_type = models.CharField(max_length=50)
    channel = models.CharField(max_length=20)
    recipient = models.CharField(max_length=255)
    delivery_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    retry_count = models.PositiveIntegerField(default=0)
    last_attempt = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.channel}] to {self.recipient} - {self.delivery_status} ({self.event_type})"


class OutboxEvent(models.Model):
    """
    Transactional Outbox Pattern.
    Guarantees reliable, at-least-once asynchronous event delivery
    to n8n workflows, WhatsApp webhooks, and calendar sync without
    failing the user HTTP request.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    event_id = models.CharField(max_length=64, unique=True, db_index=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='outbox_events')
    event_type = models.CharField(max_length=50, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    retry_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.event_id}: {self.event_type} ({self.status}) for {self.business.name}"
