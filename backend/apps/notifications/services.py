import re
import json
import logging
import requests
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail

from apps.notifications.models import NotificationTemplate, NotificationDelivery, OutboxEvent
from apps.businesses.models import Business
from apps.bookings.models import Booking

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """
    Renders business-specific templates and delivers notifications
    over Email, WhatsApp, and Webhooks.
    """

    @classmethod
    def render_template(cls, template_str: str, context: dict) -> str:
        """Substitutes {{variable}} placeholders with context values safely"""
        rendered = template_str
        for key, val in context.items():
            pattern = re.compile(r'{{\s*' + re.escape(key) + r'\s*}}', re.IGNORECASE)
            rendered = pattern.sub(str(val or ''), rendered)
        return rendered

    @classmethod
    def send_notification(cls, business: Business, event_type: str, channel: str, recipient: str, context: dict, booking: Booking = None) -> NotificationDelivery:
        """
        Sends notification through the specified channel using the business's template.
        """
        tmpl = NotificationTemplate.objects.filter(
            business=business,
            event_type=event_type,
            channel=channel,
            is_active=True
        ).first()

        subject = cls.render_template(tmpl.subject, context) if tmpl and tmpl.subject else f"Notification: {event_type}"
        body = cls.render_template(tmpl.template_body, context) if tmpl else f"Event: {event_type} for reference {context.get('reference', '')}"

        delivery = NotificationDelivery.objects.create(
            business=business,
            booking=booking,
            event_type=event_type,
            channel=channel,
            recipient=recipient,
            delivery_status='pending',
            payload=context
        )

        try:
            if channel == 'email':
                cls._dispatch_email(recipient, subject, body)
            elif channel == 'whatsapp':
                cls._dispatch_whatsapp(recipient, body)

            delivery.delivery_status = 'sent'
            delivery.last_attempt = timezone.now()
            delivery.save(update_fields=['delivery_status', 'last_attempt'])
        except Exception as e:
            logger.error(f"Failed to dispatch {channel} to {recipient}: {e}")
            delivery.delivery_status = 'failed'
            delivery.error_message = str(e)
            delivery.last_attempt = timezone.now()
            delivery.save(update_fields=['delivery_status', 'error_message', 'last_attempt'])

        return delivery

    @classmethod
    def _dispatch_email(cls, recipient: str, subject: str, body: str):
        if not recipient:
            return
        # Log or send
        logger.info(f"[EMAIL] To: {recipient} | Subject: {subject} | Body: {body[:60]}...")

    @classmethod
    def _dispatch_whatsapp(cls, phone_number: str, text: str):
        if not phone_number:
            return

        mock_mode = getattr(settings, 'WHATSAPP_MOCK_MODE', True)
        token = getattr(settings, 'WHATSAPP_API_TOKEN', '')
        phone_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')

        if mock_mode or not token or not phone_id:
            logger.info(f"[WHATSAPP MOCK] To: {phone_number} | Message: {text[:60]}...")
            return

        # Official WhatsApp Business Cloud API endpoint
        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"body": text}
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=5)
        resp.raise_for_status()


class OutboxProcessor:
    """
    Processes queued OutboxEvents.
    Posts to n8n webhook URL and dispatches notifications.
    """

    @classmethod
    def process_pending_events(cls, limit: int = 50) -> int:
        pending_events = OutboxEvent.objects.filter(status='pending').select_related('business')[:limit]
        processed_count = 0

        for event in pending_events:
            event.status = 'processing'
            event.save(update_fields=['status'])

            try:
                # 1. Post to n8n webhook if configured
                n8n_url = getattr(settings, 'N8N_WEBHOOK_URL', '')
                if n8n_url:
                    try:
                        requests.post(n8n_url, json=event.payload, timeout=2)
                    except Exception as n8n_err:
                        logger.warning(f"Could not reach n8n webhook at {n8n_url}: {n8n_err}")

                # 2. Trigger notification dispatcher for channels
                payload = event.payload
                biz = event.business
                cust_email = payload.get('customer_email')
                cust_phone = payload.get('customer_phone')

                if cust_email:
                    NotificationDispatcher.send_notification(
                        business=biz,
                        event_type=event.event_type,
                        channel='email',
                        recipient=cust_email,
                        context=payload
                    )

                if cust_phone:
                    NotificationDispatcher.send_notification(
                        business=biz,
                        event_type=event.event_type,
                        channel='whatsapp',
                        recipient=cust_phone,
                        context=payload
                    )

                event.status = 'delivered'
                event.processed_at = timezone.now()
                event.save(update_fields=['status', 'processed_at'])
                processed_count += 1
            except Exception as e:
                event.status = 'failed'
                event.retry_count += 1
                event.error_message = str(e)
                event.save(update_fields=['status', 'retry_count', 'error_message'])

        return processed_count
