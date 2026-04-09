"""
AbiCare — Storage Backends
============================
DESIGN PRINCIPLE: This file NEVER crashes the application.

If credentials are missing, wrong, or the remote service is unreachable,
the system silently falls back to local disk storage and logs a warning.
The app continues to work normally. Once credentials are correct, run
  python manage.py sync_media_to_storage
and everything migrates to the cloud.

Supported backends (STORAGE_BACKEND in .env):
  local    - disk on this server (default, always works, no config needed)
  r2       - Cloudflare R2 (recommended for Railway, no egress fees)
  s3       - Amazon S3
  b2       - Backblaze B2
  railway  - alias for r2/S3-compatible
  azure    - Azure Blob Storage (hot / cool / archive tiers)
"""

import logging
import os

from django.core.files.storage import FileSystemStorage

logger = logging.getLogger('abicare.storage')

# ── Try to import optional storage libraries ──────────────────────────────────
# If not installed, we fall back to local disk silently.
try:
    from storages.backends.s3boto3 import S3Boto3Storage
    HAS_S3 = True
except ImportError:
    HAS_S3 = False

try:
    from storages.backends.azure_storage import AzureStorage
    HAS_AZURE = True
except ImportError:
    HAS_AZURE = False


def _missing(varname):
    """True if an env var is absent or blank."""
    return not os.environ.get(varname, '').strip()


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL FALLBACK — used whenever cloud backend cannot be initialised
# ─────────────────────────────────────────────────────────────────────────────

class LocalFallbackStorage(FileSystemStorage):
    """
    Transparent local-disk storage.
    Logs a one-time warning so you know why cloud is not active.
    """
    _warned = False

    def __init__(self, *args, **kwargs):
        if not LocalFallbackStorage._warned:
            logger.warning(
                "AbiCare storage: LOCAL DISK active. "
                "Files go to MEDIA_ROOT on this server. "
                "Set cloud credentials in .env and restart to switch."
            )
            LocalFallbackStorage._warned = True
        super().__init__(*args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# S3-COMPATIBLE BACKEND (Cloudflare R2 / AWS S3 / Backblaze B2 / Railway)
# Falls back silently to local disk if anything is wrong.
# ─────────────────────────────────────────────────────────────────────────────

def _make_s3():
    """Build the S3Boto3Storage instance. Raises on any problem."""
    class _S3Media(S3Boto3Storage):
        location         = 'media'
        file_overwrite   = False
        default_acl      = 'private'
        querystring_auth = True
    return _S3Media()


def _s3_or_local():
    """Return S3 backend if possible, otherwise LocalFallbackStorage."""
    if not HAS_S3:
        logger.warning(
            "django-storages or boto3 not installed — using local disk. "
            "Add to requirements.txt: django-storages[s3]==1.14.3 boto3==1.34.0"
        )
        return LocalFallbackStorage

    missing = [v for v in (
        'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_STORAGE_BUCKET_NAME'
    ) if _missing(v)]

    if missing:
        logger.warning(
            "Object storage credentials missing: %s — using local disk. "
            "Set these in .env to activate cloud storage.",
            ', '.join(missing)
        )
        return LocalFallbackStorage

    try:
        _make_s3()   # test that it can be constructed
        logger.info(
            "S3 storage active: bucket=%s endpoint=%s",
            os.environ.get('AWS_STORAGE_BUCKET_NAME'),
            os.environ.get('AWS_S3_ENDPOINT_URL', 'AWS default'),
        )
        return type('MediaStorage', (object,), {
            '__new__': staticmethod(lambda cls, *a, **kw: _make_s3())
        })
    except Exception as exc:
        logger.error(
            "S3 backend initialisation failed: %s — falling back to local disk.", exc
        )
        return LocalFallbackStorage


# ─────────────────────────────────────────────────────────────────────────────
# AZURE BACKENDS
# ─────────────────────────────────────────────────────────────────────────────

def _make_azure(container_env, default_container):
    """Build an AzureStorage instance. Raises on any problem."""
    class _AzureMedia(AzureStorage):
        account_name    = os.environ.get('AZURE_ACCOUNT_NAME', '')
        account_key     = os.environ.get('AZURE_ACCOUNT_KEY', '')
        azure_container = os.environ.get(container_env, default_container)
        overwrite_files = False
    return _AzureMedia()


def _azure_or_local(container_env, default_container):
    """Return Azure backend if possible, otherwise LocalFallbackStorage."""
    if not HAS_AZURE:
        logger.warning(
            "azure-storage-blob not installed — using local disk. "
            "Run: pip install azure-storage-blob azure-identity"
        )
        return LocalFallbackStorage

    missing = [v for v in ('AZURE_ACCOUNT_NAME', 'AZURE_ACCOUNT_KEY') if _missing(v)]
    if missing:
        logger.warning(
            "Azure credentials missing: %s — using local disk.", ', '.join(missing)
        )
        return LocalFallbackStorage

    try:
        _make_azure(container_env, default_container)
        logger.info(
            "Azure storage active: account=%s container=%s",
            os.environ.get('AZURE_ACCOUNT_NAME'),
            os.environ.get(container_env, default_container),
        )
        _env  = container_env
        _def  = default_container
        return type('_AzureBackend', (object,), {
            '__new__': staticmethod(lambda cls, *a, **kw: _make_azure(_env, _def))
        })
    except Exception as exc:
        logger.error("Azure storage init failed: %s — local disk.", exc)
        return LocalFallbackStorage


# Public classes — settings.py points DEFAULT_FILE_STORAGE at these
# Each one picks the real backend or falls back transparently.

class MediaStorage(FileSystemStorage):
    """S3-compatible media storage with silent local fallback."""
    def __new__(cls, *args, **kwargs):
        klass = _s3_or_local()
        return object.__new__(klass) if klass is not LocalFallbackStorage \
               else LocalFallbackStorage(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        pass  # __new__ returns the right object; __init__ is bypassed for that object


class AzureMediaStorage(FileSystemStorage):
    """Azure Blob — Hot tier — with silent local fallback."""
    def __new__(cls, *args, **kwargs):
        klass = _azure_or_local('AZURE_MEDIA_CONTAINER', 'abicare-media')
        return object.__new__(klass) if klass is not LocalFallbackStorage \
               else LocalFallbackStorage(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        pass


class AzureCoolStorage(FileSystemStorage):
    """Azure Blob — Cool tier — with silent local fallback."""
    def __new__(cls, *args, **kwargs):
        klass = _azure_or_local('AZURE_COOL_CONTAINER', 'abicare-cool')
        return object.__new__(klass) if klass is not LocalFallbackStorage \
               else LocalFallbackStorage(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        pass


class AzureArchiveStorage(FileSystemStorage):
    """Azure Blob — Archive tier — with silent local fallback."""
    def __new__(cls, *args, **kwargs):
        klass = _azure_or_local('AZURE_ARCHIVE_CONTAINER', 'abicare-archive')
        return object.__new__(klass) if klass is not LocalFallbackStorage \
               else LocalFallbackStorage(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK helper (used by storage_status management command)
# ─────────────────────────────────────────────────────────────────────────────

def get_storage_status():
    """Returns a plain dict describing current storage state."""
    backend = os.environ.get('STORAGE_BACKEND', 'local').lower()

    if backend == 'local':
        return {'backend': 'local', 'status': 'active',
                'ready': True, 'note': 'Local disk (MEDIA_ROOT)'}

    if backend in ('railway', 's3', 'r2', 'b2'):
        if not HAS_S3:
            return {'backend': backend, 'status': 'fallback', 'ready': False,
                    'note': 'Local disk — install django-storages[s3] boto3'}
        missing = [v for v in (
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_STORAGE_BUCKET_NAME'
        ) if _missing(v)]
        if missing:
            return {'backend': backend, 'status': 'fallback', 'ready': False,
                    'note': f'Local disk — missing .env vars: {", ".join(missing)}'}
        return {'backend': backend, 'status': 'active', 'ready': True,
                'note': f"Bucket: {os.environ.get('AWS_STORAGE_BUCKET_NAME')}"}

    if backend == 'azure':
        if not HAS_AZURE:
            return {'backend': 'azure', 'status': 'fallback', 'ready': False,
                    'note': 'Local disk — install azure-storage-blob'}
        missing = [v for v in ('AZURE_ACCOUNT_NAME', 'AZURE_ACCOUNT_KEY') if _missing(v)]
        if missing:
            return {'backend': 'azure', 'status': 'fallback', 'ready': False,
                    'note': f'Local disk — missing .env vars: {", ".join(missing)}'}
        return {'backend': 'azure', 'status': 'active', 'ready': True,
                'note': f"Account: {os.environ.get('AZURE_ACCOUNT_NAME')}"}

    return {'backend': backend, 'status': 'unknown', 'ready': False,
            'note': f'Unrecognised STORAGE_BACKEND value — using local disk'}