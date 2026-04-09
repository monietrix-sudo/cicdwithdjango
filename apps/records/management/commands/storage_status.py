"""
AbiCare — Management Command: storage_status
=============================================
Shows the current storage backend configuration and whether
cloud credentials are present and working.

Usage:
    python manage.py storage_status
    python manage.py storage_status --test-upload
"""
import os
import tempfile
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Shows the current file storage backend status and configuration.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--test-upload',
            action='store_true',
            help='Actually upload and delete a tiny test file to verify the backend works.',
        )

    def handle(self, *args, **options):
        from abicare.storage_backends import get_storage_status

        status = get_storage_status()
        self.stdout.write('')
        self.stdout.write('─' * 60)
        self.stdout.write('  AbiCare File Storage Status')
        self.stdout.write('─' * 60)

        backend = status['backend']
        ready   = status['ready']
        note    = status['note']
        st      = status['status']

        # Backend
        self.stdout.write(f"  Backend       : {backend.upper()}")

        # Status with colour
        if st == 'active' and ready:
            self.stdout.write(
                f"  Status        : " + self.style.SUCCESS("ACTIVE — cloud storage working")
            )
        elif st == 'fallback':
            self.stdout.write(
                f"  Status        : " + self.style.WARNING("FALLBACK — using local disk")
            )
        else:
            self.stdout.write(f"  Status        : {st}")

        self.stdout.write(f"  Detail        : {note}")
        self.stdout.write(f"  MEDIA_ROOT    : {settings.MEDIA_ROOT}")
        self.stdout.write(f"  MEDIA_URL     : {settings.MEDIA_URL}")

        # Show relevant env vars (masked)
        self.stdout.write('')
        self.stdout.write('  Environment variables:')

        def show_var(name, mask=True):
            val = os.environ.get(name, '')
            if not val:
                display = self.style.ERROR('  (not set)')
            elif mask and len(val) > 8:
                display = val[:4] + '***' + val[-4:]
            else:
                display = self.style.SUCCESS(val)
            self.stdout.write(f"    {name:<35} {display}")

        if backend in ('railway', 's3', 'r2', 'b2'):
            show_var('STORAGE_BACKEND', mask=False)
            show_var('AWS_ACCESS_KEY_ID')
            show_var('AWS_SECRET_ACCESS_KEY')
            show_var('AWS_STORAGE_BUCKET_NAME', mask=False)
            show_var('AWS_S3_REGION_NAME', mask=False)
            show_var('AWS_S3_ENDPOINT_URL', mask=False)
            show_var('AWS_QUERYSTRING_EXPIRE', mask=False)
        elif backend == 'azure':
            show_var('STORAGE_BACKEND', mask=False)
            show_var('AZURE_ACCOUNT_NAME', mask=False)
            show_var('AZURE_ACCOUNT_KEY')
            show_var('AZURE_MEDIA_CONTAINER', mask=False)
        else:
            show_var('STORAGE_BACKEND', mask=False)

        # Optional test upload
        if options['test_upload']:
            self.stdout.write('')
            self.stdout.write('  Test upload...')
            self._test_upload()

        self.stdout.write('')

        # Next steps
        if not ready:
            self.stdout.write('─' * 60)
            self.stdout.write(self.style.WARNING('  To activate cloud storage:'))
            self.stdout.write(
                '  1. Set STORAGE_BACKEND=r2 (or s3/b2/azure) in .env'
            )
            self.stdout.write(
                '  2. Set the relevant credentials (see .env.example)'
            )
            self.stdout.write(
                '  3. pip install "django-storages[s3]" boto3'
            )
            self.stdout.write(
                '  4. Restart the server'
            )
            self.stdout.write(
                '  5. python manage.py sync_media_to_storage'
            )
            self.stdout.write('')
            self.stdout.write(
                self.style.SUCCESS(
                    '  The app works fine on local storage in the meantime.'
                )
            )
        self.stdout.write('─' * 60)

    def _test_upload(self):
        """Upload a tiny test file and immediately delete it."""
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile

        test_key = '_abicare_storage_test/test.txt'
        test_content = b'AbiCare storage test file. Safe to delete.'

        try:
            # Upload
            saved_path = default_storage.save(test_key, ContentFile(test_content))
            self.stdout.write(
                '    Upload    : ' + self.style.SUCCESS(f'OK — {saved_path}')
            )

            # Read back
            with default_storage.open(saved_path) as f:
                data = f.read()
            assert data == test_content, "Content mismatch after upload"
            self.stdout.write(
                '    Read-back : ' + self.style.SUCCESS('OK — content verified')
            )

            # Generate URL
            url = default_storage.url(saved_path)
            self.stdout.write(
                f'    File URL  : {url[:80]}{"…" if len(url) > 80 else ""}'
            )

            # Delete
            default_storage.delete(saved_path)
            self.stdout.write(
                '    Delete    : ' + self.style.SUCCESS('OK — test file removed')
            )
            self.stdout.write(
                '    ' + self.style.SUCCESS(
                    'Storage backend is working correctly.'
                )
            )

        except Exception as exc:
            self.stdout.write(
                '    ' + self.style.ERROR(f'FAILED: {exc}')
            )
            self.stdout.write(
                '    Check your credentials and bucket/container settings.'
            )