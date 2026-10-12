from django.core.management.base import BaseCommand, CommandError
from portal.discovery import scan_reports

class Command(BaseCommand):
    help = 'Discover reports and supplements. Run offline; the live app owns its DuckDB file.'
    def handle(self, **options):
        try:
            count, errors = scan_reports()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f'Indexed {count} published deliverable(s).')
        for error in errors:
            self.stderr.write(error)
        if errors:
            raise CommandError(f'{len(errors)} deliverable(s) failed validation and were unpublished.')
