"""
AbiCare Hospital EHR - Settings
================================
Reads sensitive values from .env file using python-dotenv.
Install: pip install python-dotenv

Database-agnostic: set DB_ENGINE in .env to switch between
PostgreSQL, MySQL, or SQLite without changing any code.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Load .env file ────────────────────────────────────────────────────
# load_dotenv() reads every key=value from .env and puts it into
# os.environ so os.getenv() can read it anywhere in this file.
# If .env does not exist it does nothing — no crash.
load_dotenv(BASE_DIR / '.env')


# ── Helper functions ──────────────────────────────────────────────────
def env(key, default=''):
    """Read a string value from .env / environment."""
    return os.getenv(key, default)


def env_bool(key, default=False):
    """Read a True/False value from .env / environment."""
    return os.getenv(key, str(default)).lower() in ('true', '1', 'yes')


def env_int(key, default=0):
    """Read an integer value from .env / environment."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def env_list(key, default=''):
    """Read a comma-separated list from .env / environment."""
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(',') if item.strip()]


# ── Core Security ─────────────────────────────────────────────────────
SECRET_KEY    = env('DJANGO_SECRET_KEY', 'dev-key-change-in-production-abc123xyz')
DEBUG         = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')


# ── Hospital Branding — change here to rebrand ────────────────────────
HOSPITAL_NAME          = "AbiCare Hospital"
HOSPITAL_TAGLINE       = "Compassionate Care, Advanced Medicine"
HOSPITAL_ADDRESS       = "123 Medical Drive, Lagos, Nigeria"
HOSPITAL_PHONE         = "+234 800 000 0000"
HOSPITAL_EMAIL         = "info@abicarehospital.com"
HOSPITAL_LOGO          = "images/abicare-logo.png"
HOSPITAL_PRIMARY_COLOR = "#0A5C8A"
HOSPITAL_ACCENT_COLOR  = "#00C49A"
HOSPITAL_WEBSITE       = "https://abicarehospital.com"


# ── Installed Apps ────────────────────────────────────────────────────
INSTALLED_APPS = [
    'jazzmin',                          # must be FIRST before django.contrib.admin
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'crispy_forms',
    'crispy_bootstrap5',
    'widget_tweaks',
    'apps.accounts',
    'apps.patients',
    'apps.appointments',
    'apps.lab_results',
    'apps.medications',
    'apps.teleconsult',
    'apps.audit_logs',
    'apps.records',
    'apps.notifications',
    'apps.queue',
    'apps.portal',
    'apps.families',
    'apps.imports',
    'apps.clinical_records',
    'apps.billing',
    'apps.role_portals',
    'apps.nursing',
]


# ── Middleware ────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.audit_logs.middleware.AdminReAuthMiddleware',
    'apps.audit_logs.middleware.AuditMiddleware',
]


ROOT_URLCONF     = 'abicare.urls'
WSGI_APPLICATION = 'abicare.wsgi.application'


# ── Templates ─────────────────────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS':    [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'abicare.context_processors.hospital_settings',
            ],
        },
    },
]


# ── Database ──────────────────────────────────────────────────────────
# Set DB_ENGINE in .env to switch databases without touching this file.
# Options:
#   django.db.backends.sqlite3      (default, good for development)
#   django.db.backends.postgresql   (recommended for production)
#   django.db.backends.mysql

_DB_ENGINE = env('DB_ENGINE', 'django.db.backends.sqlite3')

if _DB_ENGINE == 'django.db.backends.sqlite3':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME':   BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE':   _DB_ENGINE,
            'NAME':     env('DB_NAME',     'abicare_ehr'),
            'USER':     env('DB_USER',     'abicare_user'),
            'PASSWORD': env('DB_PASSWORD', ''),
            'HOST':     env('DB_HOST',     'localhost'),
            'PORT':     env('DB_PORT',     '5432'),
        }
    }


# ── Authentication ────────────────────────────────────────────────────
AUTH_USER_MODEL     = 'accounts.User'
LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/dashboard/'   # staff default — patients redirect to /portal/ in login_view
LOGOUT_REDIRECT_URL = '/accounts/login/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ── Localisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Lagos'
USE_I18N      = True
USE_TZ        = True


# ── Static & Media Files ──────────────────────────────────────────────
# Static files (CSS, JS, admin) — served by WhiteNoise in production
STATIC_URL       = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT      = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ── Object Storage Configuration ─────────────────────────────────────
# Controls WHERE uploaded files (PDFs, images, patient photos) are stored.
# Set STORAGE_BACKEND in .env to switch backends with zero code changes.
#
# STORAGE_BACKEND=local      → disk on this server (dev/testing only)
# STORAGE_BACKEND=railway    → Railway S3-compatible bucket   ← use this on Railway
# STORAGE_BACKEND=s3         → Amazon S3
# STORAGE_BACKEND=r2         → Cloudflare R2 (S3-compatible, cheaper)
# STORAGE_BACKEND=b2         → Backblaze B2 (S3-compatible, cheapest)
# STORAGE_BACKEND=azure      → Azure Blob Storage

STORAGE_BACKEND = env('STORAGE_BACKEND', 'local').lower()

# ── Local storage (default — dev only) ───────────────────────────────
MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── S3-compatible (Railway / AWS S3 / Cloudflare R2 / Backblaze B2) ──
# Railway:     get these from Railway dashboard → your project → Storage tab → Connect
# AWS S3:      leave AWS_S3_ENDPOINT_URL empty
# Cloudflare R2: endpoint = https://<account_id>.r2.cloudflarestorage.com
# Backblaze B2:  endpoint = https://s3.<region>.backblazeb2.com

AWS_ACCESS_KEY_ID        = env('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY    = env('AWS_SECRET_ACCESS_KEY', '')
AWS_STORAGE_BUCKET_NAME  = env('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_REGION_NAME       = env('AWS_S3_REGION_NAME', 'us-east-1')
AWS_S3_ENDPOINT_URL      = env('AWS_S3_ENDPOINT_URL', '')    # blank = real AWS; set for Railway/R2/B2

# How long signed download URLs stay valid (seconds). Default = 1 hour.
# Files are private — Django generates a fresh signed URL each time a file is accessed.
AWS_QUERYSTRING_EXPIRE   = env_int('AWS_QUERYSTRING_EXPIRE', 3600)

# Prevent django-storages from adding query-string parameters to static URLs
AWS_S3_FILE_OVERWRITE    = False      # don't silently overwrite existing files
AWS_DEFAULT_ACL          = 'private' # all uploaded files are private by default

# Extra headers for better browser behaviour
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',           # browser caches files for 1 day
}

# ── Azure Blob Storage ────────────────────────────────────────────────
# Get these from Azure Portal → Storage Account → Access Keys
# Tiers: "Hot" = fast/expensive, "Cool" = slower/cheaper, "Archive" = offline/cheapest
AZURE_ACCOUNT_NAME      = env('AZURE_ACCOUNT_NAME', '')
AZURE_ACCOUNT_KEY       = env('AZURE_ACCOUNT_KEY', '')
AZURE_MEDIA_CONTAINER   = env('AZURE_MEDIA_CONTAINER', 'abicare-media')
AZURE_COOL_CONTAINER    = env('AZURE_COOL_CONTAINER', 'abicare-cool')
AZURE_ARCHIVE_CONTAINER = env('AZURE_ARCHIVE_CONTAINER', 'abicare-archive')

# ── Django storages routing ───────────────────────────────────────────
# Switch DEFAULT_FILE_STORAGE based on STORAGE_BACKEND env var.
# The database always stores only the file path — never the file bytes.
# Changing storage backend does not change the database schema at all.

if STORAGE_BACKEND == 'local':
    # Files on disk — MEDIA_ROOT set above
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

elif STORAGE_BACKEND in ('railway', 's3', 'r2', 'b2'):
    # S3-compatible — MediaStorage handles missing creds by falling back to local
    DEFAULT_FILE_STORAGE = 'abicare.storage_backends.MediaStorage'
    # Update MEDIA_URL to point at the bucket (only if bucket name is set)
    _bucket = env('AWS_STORAGE_BUCKET_NAME', '')
    _endpoint = env('AWS_S3_ENDPOINT_URL', '')
    if _bucket:
        if _endpoint:
            MEDIA_URL = f'{_endpoint.rstrip("/")}/{_bucket}/media/'
        else:
            _region = env('AWS_S3_REGION_NAME', 'us-east-1')
            MEDIA_URL = f'https://{_bucket}.s3.{_region}.amazonaws.com/media/'
    # If bucket name is not set yet, keep MEDIA_URL as /media/ — local fallback active

elif STORAGE_BACKEND == 'azure':
    # Azure Blob — AzureMediaStorage handles missing creds by falling back to local
    DEFAULT_FILE_STORAGE = 'abicare.storage_backends.AzureMediaStorage'
    _az_account   = env('AZURE_ACCOUNT_NAME', '')
    _az_container = env('AZURE_MEDIA_CONTAINER', 'abicare-media')
    if _az_account:
        MEDIA_URL = (
            f'https://{_az_account}.blob.core.windows.net/{_az_container}/media/'
        )

else:
    # Unknown value — log at startup and stay on local disk
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
    import logging as _log
    _log.getLogger('abicare.storage').warning(
        "Unknown STORAGE_BACKEND='%s'. Valid: local, r2, s3, b2, railway, azure. "
        "Using local disk.", STORAGE_BACKEND
    )


# ── File Upload Limits ────────────────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024   # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_UPLOAD_SIZE             = 50 * 1024 * 1024   # 50 MB

ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
ALLOWED_DOC_TYPES   = ['application/pdf', 'application/msword',
                       'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
ALLOWED_VIDEO_TYPES = ['video/mp4', 'video/webm', 'video/ogg']


# ── Session & Security ────────────────────────────────────────────────
SESSION_COOKIE_AGE              = 28800   # 8 hours
SESSION_COOKIE_SECURE           = not DEBUG
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SECURE              = not DEBUG
SECURE_BROWSER_XSS_FILTER       = True
SECURE_CONTENT_TYPE_NOSNIFF     = True
X_FRAME_OPTIONS                 = 'DENY'
SECURE_HSTS_SECONDS             = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS  = not DEBUG
SECURE_HSTS_PRELOAD             = not DEBUG


# ── Email ─────────────────────────────────────────────────────────────
# Development: EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
#   → prints emails to terminal instead of sending them
# Production:  EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
#   → actually sends via Gmail SMTP
EMAIL_BACKEND       = env('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST          = env('EMAIL_HOST',    'smtp.gmail.com')
EMAIL_PORT          = env_int('EMAIL_PORT', 587)
EMAIL_USE_TLS       = True
EMAIL_HOST_USER     = env('EMAIL_HOST_USER',     '')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL  = f"{HOSPITAL_NAME} <{HOSPITAL_EMAIL}>"


# ── Crispy Forms ──────────────────────────────────────────────────────
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK          = 'bootstrap5'


# ── Twilio WhatsApp (optional — leave blank to disable) ───────────────
# If these are blank the system works fine. WhatsApp is silently skipped.
TWILIO_ACCOUNT_SID   = env('TWILIO_ACCOUNT_SID',   '')
TWILIO_AUTH_TOKEN    = env('TWILIO_AUTH_TOKEN',    '')
TWILIO_WHATSAPP_FROM = env('TWILIO_WHATSAPP_FROM', '')


# ── Tesseract OCR (optional — system works fine without it) ───────────
TESSERACT_CMD   = env('TESSERACT_CMD', 'tesseract')
HAS_PYTESSERACT = False
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    HAS_PYTESSERACT = True
except ImportError:
    pass  # OCR button will show install instructions if clicked


# ── Jazzmin Admin Theme ───────────────────────────────────────────────
JAZZMIN_SETTINGS = {
    "site_title":   f"{HOSPITAL_NAME} Admin",
    "site_header":   HOSPITAL_NAME,
    "site_brand":    HOSPITAL_NAME,
    "welcome_sign": f"Welcome to {HOSPITAL_NAME} Administration",
    "copyright":    f"© 2024 {HOSPITAL_NAME}",
    "search_model": ["accounts.User", "patients.Patient"],
    "topmenu_links": [
        {"name": "EHR Dashboard", "url": "/dashboard/",    "permissions": ["auth.view_user"]},
        {"name": "Patients",      "url": "/patients/",     "permissions": ["auth.view_user"]},
        {"name": "Appointments",  "url": "/appointments/", "permissions": ["auth.view_user"]},
        {"name": "Lab Results",   "url": "/lab-results/",  "permissions": ["auth.view_user"]},
    ],
    "show_sidebar":        True,
    "navigation_expanded": True,
    "order_with_respect_to": [
        "accounts", "patients", "appointments",
        "lab_results", "medications", "records",
        "teleconsult", "audit_logs", "notifications", "queue",
    ],
    "icons": {
        "auth":                           "fas fa-users-cog",
        "accounts.User":                  "fas fa-user",
        "patients.Patient":               "fas fa-hospital-user",
        "appointments.Appointment":       "fas fa-calendar-check",
        "lab_results.LabTemplate":        "fas fa-file-medical-alt",
        "lab_results.LabResult":          "fas fa-flask",
        "medications.MedicationSchedule": "fas fa-pills",
        "medications.MedicationDose":     "fas fa-clock",
        "records.MedicalRecord":          "fas fa-file-medical",
        "audit_logs.AuditLog":            "fas fa-history",
        "teleconsult.ConsultLink":        "fas fa-video",
        "notifications.Notification":     "fas fa-bell",
        "queue.QueueEntry":               "fas fa-users-cog",
    },
    "default_icon_parents":  "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    "related_modal_active":  True,
    "custom_css":            "css/admin_custom.css",
    "use_google_fonts_cdn":  True,
    "show_ui_builder":       False,
    "changeform_format":     "horizontal_tabs",
    "language_chooser":      False,
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text":         False,
    "body_small_text":           False,
    "brand_colour":              "navbar-primary",
    "accent":                    "accent-teal",
    "navbar":                    "navbar-dark",
    "navbar_fixed":              True,
    "sidebar_fixed":             True,
    "sidebar":                   "sidebar-dark-primary",
    "sidebar_nav_compact_style": False,
    "sidebar_nav_flat_style":    False,
    "theme":                     "default",
    "button_classes": {
        "primary":   "btn-primary",
        "secondary": "btn-secondary",
        "info":      "btn-info",
        "warning":   "btn-warning",
        "danger":    "btn-danger",
        "success":   "btn-success",
    },
    "actions_sticky_top": True,
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Paystack (Nigeria payments) ────────────────────────────────────────
PAYSTACK_SECRET_KEY = env('PAYSTACK_SECRET_KEY', '')
PAYSTACK_PUBLIC_KEY = env('PAYSTACK_PUBLIC_KEY', '')


# ── Logging ───────────────────────────────────────────────────────────────
# Routes the abicare.storage logger to the console so storage warnings
# (e.g. "using local disk fallback") appear in Railway logs.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'abicare': {
            'format': '[{levelname}] {name}: {message}',
            'style':  '{',
        },
    },
    'handlers': {
        'console': {
            'class':     'logging.StreamHandler',
            'formatter': 'abicare',
        },
    },
    'loggers': {
        # AbiCare storage — shows fallback warnings when cloud is not configured
        'abicare.storage': {
            'handlers': ['console'],
            'level':    'WARNING',
            'propagate': False,
        },
        # Django errors always go to console
        'django': {
            'handlers': ['console'],
            'level':    env('DJANGO_LOG_LEVEL', 'WARNING'),
            'propagate': False,
        },
    },
}

CSRF_TRUSTED_ORIGINS = [
    "https://abicarehospital-production.up.railway.app",
    "https://*.railway.app",  # This covers any other railway subdomains
]
