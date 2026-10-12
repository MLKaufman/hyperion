from getpass import getpass
import duckdb
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from portal.auth import create_user, username_key
from portal.db import db


class Command(BaseCommand):
    help = 'Create a local administrator while the application is stopped.'

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, username, **options):
        username = username_key(username)
        if not username or len(username) > 150:
            raise CommandError('Username must contain 1–150 characters.')
        if db().one('SELECT id FROM users WHERE username=?', [username]):
            raise CommandError(
                f'Account "{username}" already exists. Sign in with that account, '
                'or choose a different username. No password was changed.'
            )
        self.stdout.write('Use at least 12 characters; avoid common or entirely numeric passwords.')
        password = getpass('Password: ')
        if password != getpass('Confirm password: '):
            raise CommandError('Passwords do not match. No account was created.')
        try:
            create_user(username, password, admin=True, temporary=False)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages) + ' No account was created.') from exc
        except duckdb.ConstraintException as exc:
            raise CommandError(
                f'Account "{username}" could not be created because of a database constraint. '
                'The username may have been added already. No existing account was changed.'
            ) from exc
        self.stdout.write(f'Administrator "{username}" created.')
