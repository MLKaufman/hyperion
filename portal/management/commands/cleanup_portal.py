from django.core.management.base import BaseCommand
from portal.maintenance import cleanup

class Command(BaseCommand):
    help = 'Offline cleanup of expired DuckDB sessions, grants, and ZIP caches.'
    def handle(self, **options):
        cleanup()
        self.stdout.write('Expired state cleaned.')
