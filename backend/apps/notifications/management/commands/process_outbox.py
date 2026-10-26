from django.core.management.base import BaseCommand
from apps.notifications.services import OutboxProcessor


class Command(BaseCommand):
    help = 'Processes pending Outbox events and dispatches notifications and n8n webhooks.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50, help='Max events to process')

    def handle(self, *args, **options):
        limit = options['limit']
        count = OutboxProcessor.process_pending_events(limit=limit)
        self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} outbox events."))
