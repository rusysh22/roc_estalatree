"""Development settings."""
from pathlib import Path

import environ

# Read .env BEFORE importing base so env vars are available when base.py loads.
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    environ.Env.read_env(str(_env_file))

from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Disable password validators in dev for convenience
AUTH_PASSWORD_VALIDATORS = []

# Use console email in dev (already default in base, but explicit here)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# django-debug-toolbar (optional, install separately if needed)
INTERNAL_IPS = ["127.0.0.1"]
