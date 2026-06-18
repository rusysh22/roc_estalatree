"""Production settings."""
from .base import *  # noqa: F401, F403

DEBUG = False

# Security hardening
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# Email: configure via env in production
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
