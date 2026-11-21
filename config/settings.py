"""Environment-based settings; production configuration fails closed."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT = os.environ.get("FORMREVIEW_ENV", "development")
if ENVIRONMENT not in {"development", "production"}:
    raise ImproperlyConfigured("FORMREVIEW_ENV must be development or production.")

PRODUCTION = ENVIRONMENT == "production"
DEBUG = not PRODUCTION
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-not-for-production")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "local-development-only")
if PRODUCTION:
    if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("development-"):
        raise ImproperlyConfigured("Production requires a strong DJANGO_SECRET_KEY.")
    if not os.environ.get("DJANGO_ALLOWED_HOSTS") or not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("Production requires explicit DJANGO_ALLOWED_HOSTS.")
    if not DB_PASSWORD or DB_PASSWORD == "local-development-only":
        raise ImproperlyConfigured("Production requires POSTGRES_PASSWORD.")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "formreview",
    "accounts",
    "documents",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "documents.uploads.UploadAdmissionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "formreview"),
        "USER": os.environ.get("POSTGRES_USER", "formreview"),
        "PASSWORD": DB_PASSWORD,
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "TEST": {"CHARSET": "UTF8", "TEMPLATE": "template0"},
    },
}
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SECURE_SSL_REDIRECT = PRODUCTION
# Liveness is intentionally available to the container's loopback HTTP probe.
SECURE_REDIRECT_EXEMPT = [r"^health/live$"]
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

PRIVATE_ROOT = Path(os.environ.get("FORMREVIEW_PRIVATE_ROOT", str(BASE_DIR / "private")))
LOGIN_URL = "/accounts/login"
LOGIN_REDIRECT_URL = "/accounts/workspaces"
LOGOUT_REDIRECT_URL = "/accounts/login"
DATA_UPLOAD_MAX_MEMORY_SIZE = 65536
DATA_UPLOAD_MAX_NUMBER_FIELDS = 8
DATA_UPLOAD_MAX_NUMBER_FILES = 1
FILE_UPLOAD_MAX_MEMORY_SIZE = 0
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "loggers": {
        "django.request": {"handlers": ["null"], "propagate": False},
        "django.security": {"handlers": ["null"], "propagate": False},
    },
}
