"""Audit helper — write an immutable AuditLog entry."""
from django.contrib.auth import get_user_model

from apps.core.models import AuditLog


def log_action(
    action: str,
    *,
    actor=None,
    target=None,
    meta: dict | None = None,
) -> AuditLog:
    """Create an immutable AuditLog record.

    Args:
        action: Short verb string, e.g. "refund.approved", "license.revoked".
        actor: Django User instance (or None for system actions).
        target: Any model instance with pk (sets target_type + target_id).
        meta: Extra JSON payload.
    """
    target_type = ""
    target_id = ""
    if target is not None:
        target_type = type(target).__name__
        target_id = str(target.pk)

    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        meta=meta or {},
    )
