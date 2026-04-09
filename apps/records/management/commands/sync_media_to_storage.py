"""
AbiCare — Management Command: sync_media_to_storage
=====================================================
Migrates all existing locally-stored media files to the configured
object storage backend (Railway, S3, R2, B2, or Azure).

Usage:
    python manage.py sync_media_to_storage
    python manage.py sync_media_to_storage --dry-run
    python manage.py sync_media_to_storage --model records
    python manage.py sync_media_to_storage --model patients

Run this ONCE when switching from local to object storage.
After running, all new uploads go to object storage automatically.
Existing file references in the database continue to work unchanged.
"""

import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.storage import default_storage


class Command(BaseCommand):
    help = (
        'Syncs all locally stored media files to the configured object storage backend. '
        'Run once when migrating from local disk to Railway/S3/Azure.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without actually uploading anything.',
        )
        parser.add_argument(
            '--model',
            choices=['all', 'records', 'patients', 'lab_results'],
            default='all',
            help='Which model\'s files to sync (default: all).',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            default=True,
            help='Skip files that already exist in object storage (default: True).',
        )

    def handle(self, *args, **options):
        dry_run      = options['dry_run']
        model_filter = options['model']
        skip_existing = options['skip_existing']

        backend = getattr(settings, 'STORAGE_BACKEND', 'local')
        if backend == 'local':
            self.stdout.write(self.style.ERROR(
                'STORAGE_BACKEND is set to "local". '
                'Change it to "railway", "s3", "azure" etc. in .env before running this command.'
            ))
            return

        self.stdout.write(self.style.HTTP_INFO(
            f'Syncing media files to: {backend.upper()}'
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no files will be uploaded'))

        total = 0
        skipped = 0
        uploaded = 0
        failed = 0

        # Collect all FileField values from the database
        file_fields = self._collect_file_fields(model_filter)
        total = len(file_fields)

        self.stdout.write(f'Found {total} file references in database...')
        self.stdout.write('')

        for model_name, field_name, file_path in file_fields:
            if not file_path:
                skipped += 1
                continue

            # Check if file exists locally
            local_path = Path(settings.MEDIA_ROOT) / file_path
            if not local_path.exists():
                self.stdout.write(self.style.WARNING(
                    f'  MISSING locally: {file_path}'
                ))
                skipped += 1
                continue

            # Check if already in object storage
            if skip_existing and default_storage.exists(file_path):
                self.stdout.write(f'  SKIP (already in storage): {file_path}')
                skipped += 1
                continue

            self.stdout.write(
                f'  {"[DRY RUN] " if dry_run else ""}UPLOAD: {file_path} '
                f'({local_path.stat().st_size // 1024} KB)'
            )

            if not dry_run:
                try:
                    with open(local_path, 'rb') as f:
                        default_storage.save(file_path, f)
                    uploaded += 1
                    self.stdout.write(self.style.SUCCESS(f'    ✓ Uploaded'))
                except Exception as e:
                    failed += 1
                    self.stdout.write(self.style.ERROR(f'    ✗ Failed: {e}'))
            else:
                uploaded += 1

        # Summary
        self.stdout.write('')
        self.stdout.write('─' * 50)
        self.stdout.write(f'Total file references : {total}')
        self.stdout.write(self.style.SUCCESS(f'Uploaded               : {uploaded}'))
        self.stdout.write(f'Skipped                : {skipped}')
        if failed:
            self.stdout.write(self.style.ERROR(f'Failed                 : {failed}'))
        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\nDry run complete. Run without --dry-run to actually upload.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                '\nSync complete. Your .env STORAGE_BACKEND is already set — '
                'new uploads will go to object storage automatically.'
            ))

    def _collect_file_fields(self, model_filter):
        """
        Returns list of (model_name, field_name, file_path) tuples
        for all file/image fields across the relevant models.
        """
        results = []

        if model_filter in ('all', 'records'):
            from apps.records.models import MedicalRecord
            for record in MedicalRecord.objects.exclude(
                attached_file=''
            ).exclude(attached_file__isnull=True):
                results.append(('MedicalRecord', 'attached_file',
                                 record.attached_file.name))

        if model_filter in ('all', 'patients'):
            from apps.patients.models import Patient
            for patient in Patient.objects.exclude(
                photo=''
            ).exclude(photo__isnull=True):
                results.append(('Patient', 'photo', patient.photo.name))

        if model_filter in ('all', 'lab_results'):
            try:
                from apps.lab_results.models import LabResult, LabTemplate
                for result in LabResult.objects.exclude(
                    filled_pdf=''
                ).exclude(filled_pdf__isnull=True):
                    results.append(('LabResult', 'filled_pdf', result.filled_pdf.name))
                for template in LabTemplate.objects.exclude(
                    pdf_template=''
                ).exclude(pdf_template__isnull=True):
                    results.append(('LabTemplate', 'pdf_template',
                                   template.pdf_template.name))
            except Exception:
                pass  # lab_results models may have different field names

        return results