"""
AbiCare — Management Command: switch_storage
=============================================
Validates credentials, then writes the STORAGE_BACKEND value to .env
so the next server restart picks up the change.

Usage:
    python manage.py switch_storage --to r2
    python manage.py switch_storage --to local
    python manage.py switch_storage --to s3
    python manage.py switch_storage --to azure

After running this, restart the server and optionally run:
    python manage.py sync_media_to_storage
to move existing local files to the new backend.
"""
import os
import re
from pathlib import Path
from django.core.management.base import BaseCommand


VALID_BACKENDS = ('local', 'r2', 's3', 'b2', 'railway', 'azure')

REQUIRED_VARS = {
    'local':   [],
    'r2':      ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
                 'AWS_STORAGE_BUCKET_NAME', 'AWS_S3_ENDPOINT_URL'],
    's3':      ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
                 'AWS_STORAGE_BUCKET_NAME'],
    'b2':      ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
                 'AWS_STORAGE_BUCKET_NAME', 'AWS_S3_ENDPOINT_URL'],
    'railway': ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
                 'AWS_STORAGE_BUCKET_NAME', 'AWS_S3_ENDPOINT_URL'],
    'azure':   ['AZURE_ACCOUNT_NAME', 'AZURE_ACCOUNT_KEY', 'AZURE_MEDIA_CONTAINER'],
}

INSTALL_HINT = {
    'local':   None,
    'r2':      'pip install "django-storages[s3]" boto3',
    's3':      'pip install "django-storages[s3]" boto3',
    'b2':      'pip install "django-storages[s3]" boto3',
    'railway': 'pip install "django-storages[s3]" boto3',
    'azure':   'pip install azure-storage-blob azure-identity',
}


class Command(BaseCommand):
    help = (
        'Validates cloud credentials and switches the STORAGE_BACKEND in .env. '
        'Restart the server after running this command.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            required=True,
            choices=VALID_BACKENDS,
            help='Storage backend to switch to.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Switch even if credential validation fails (not recommended).',
        )
        parser.add_argument(
            '--no-test',
            action='store_true',
            help='Skip test upload (just check vars are set).',
        )

    def handle(self, *args, **options):
        target  = options['to']
        force   = options['force']
        no_test = options['no_test']

        self.stdout.write('')
        self.stdout.write(f'  Switching storage backend to: {target.upper()}')
        self.stdout.write('')

        # ── 1. Check library installed ────────────────────────────────
        hint = INSTALL_HINT.get(target)
        if hint:
            if target in ('r2', 's3', 'b2', 'railway'):
                try:
                    import boto3  # noqa: F401
                    import storages  # noqa: F401
                except ImportError:
                    self.stderr.write(self.style.ERROR(
                        f'  Required packages not installed.\n'
                        f'  Run: {hint}\n'
                        f'  Then re-run this command.'
                    ))
                    if not force:
                        return
            elif target == 'azure':
                try:
                    import azure.storage.blob  # noqa: F401
                except ImportError:
                    self.stderr.write(self.style.ERROR(
                        f'  Required packages not installed.\n'
                        f'  Run: {hint}\n'
                        f'  Then re-run this command.'
                    ))
                    if not force:
                        return

        # ── 2. Check required env vars ────────────────────────────────
        required = REQUIRED_VARS.get(target, [])
        missing = [v for v in required if not os.environ.get(v, '').strip()]

        if missing:
            self.stderr.write(self.style.ERROR(
                f'  Missing environment variables for {target.upper()}:'
            ))
            for var in missing:
                self.stderr.write(self.style.ERROR(f'    {var}  (not set)'))
            self.stdout.write('')
            self.stdout.write(
                '  Set these in your .env file, then re-run this command.'
            )
            self.stdout.write(
                '  See .env.example for descriptions of each variable.'
            )
            if not force:
                self.stdout.write('')
                self.stdout.write(
                    self.style.WARNING(
                        '  The app continues to use LOCAL DISK until credentials are set.'
                    )
                )
                return

        # ── 3. Test upload ────────────────────────────────────────────
        if not no_test and target != 'local':
            self.stdout.write('  Testing connection with a small upload...')
            ok = self._test_connection(target)
            if not ok and not force:
                self.stdout.write('')
                self.stdout.write(self.style.WARNING(
                    '  Switch cancelled. Use --force to override.'
                ))
                return

        # ── 4. Write to .env ──────────────────────────────────────────
        env_path = Path(os.getcwd()) / '.env'
        if env_path.exists():
            self._update_env_file(env_path, target)
            self.stdout.write(
                self.style.SUCCESS(f'  Updated .env: STORAGE_BACKEND={target}')
            )
        else:
            self.stdout.write(self.style.WARNING(
                f'  .env file not found at {env_path}. '
                f'Set STORAGE_BACKEND={target} manually.'
            ))

        # ── 5. Completion message ─────────────────────────────────────
        self.stdout.write('')
        self.stdout.write('─' * 60)
        self.stdout.write(self.style.SUCCESS(
            f'  Done. Restart the server to activate {target.upper()} storage.'
        ))
        if target != 'local':
            self.stdout.write(
                '  Then run:  python manage.py sync_media_to_storage'
            )
            self.stdout.write(
                '  to migrate any existing local files to the new backend.'
            )
        self.stdout.write('─' * 60)
        self.stdout.write('')

    def _test_connection(self, backend):
        """Upload a tiny test file to confirm credentials work."""
        try:
            # Temporarily force the backend so default_storage uses it
            os.environ['STORAGE_BACKEND'] = backend

            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile

            # Force re-evaluation of default_storage
            from django.core.files import storage as _storage_module
            import importlib
            importlib.reload(_storage_module)

            test_key     = '_abicare_test/connection_test.txt'
            test_content = b'AbiCare connection test. Safe to delete.'

            path = default_storage.save(test_key, ContentFile(test_content))
            default_storage.delete(path)

            self.stdout.write(
                '  ' + self.style.SUCCESS('Connection test passed.')
            )
            return True

        except Exception as exc:
            self.stdout.write(
                '  ' + self.style.ERROR(f'Connection test failed: {exc}')
            )
            self.stdout.write(
                '  Check your credentials, bucket name, and endpoint URL.'
            )
            return False

    def _update_env_file(self, env_path, new_backend):
        """Replace or add STORAGE_BACKEND line in .env."""
        content = env_path.read_text()
        pattern = re.compile(r'^STORAGE_BACKEND=.*$', re.MULTILINE)

        if pattern.search(content):
            content = pattern.sub(f'STORAGE_BACKEND={new_backend}', content)
        else:
            content += f'\nSTORAGE_BACKEND={new_backend}\n'

        env_path.write_text(content)