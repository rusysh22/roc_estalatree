"""Webhook endpoints for notification providers."""
import json
import logging

from django.core.cache import cache
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseServerError,
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.notifications import webhooks

logger = logging.getLogger(__name__)

_IDEMPOTENCY_TTL = 60 * 60 * 24  # 1 day


@csrf_exempt
@require_POST
def kirimchat_webhook(request):
    """kirim.chat delivery-status + inbound events.

    Verifies the HMAC-SHA256 signature, dedups on `event_id`, then routes the
    event. Always answers fast (< 5s) with a 2xx once accepted so kirim.chat
    doesn't retry a successfully-received event.
    """
    secret = webhooks.webhook_secret()
    if not secret:
        logger.error("kirimchat_webhook: KIRIMCHAT_WEBHOOK_SECRET not set")
        return HttpResponseServerError("Webhook not configured")

    raw = request.body
    if not webhooks.verify_signature(raw, request.headers.get(webhooks.SIGNATURE_HEADER, ""), secret):
        return HttpResponse("Invalid signature", status=401)

    try:
        payload = json.loads(raw)
    except ValueError:
        return HttpResponseBadRequest("Invalid JSON")

    event_type = payload.get("event_type") or ""
    event_id = payload.get("event_id") or ""
    data = payload.get("data") or {}

    if event_id:
        key = f"kirimchat:webhook:{event_id}"
        if not cache.add(key, "1", _IDEMPOTENCY_TTL):
            return HttpResponse("OK (duplicate)")

    try:
        webhooks.process_event(event_type, data)
    except Exception:
        logger.exception("kirimchat_webhook: error processing event_type=%s", event_type)
        return HttpResponseServerError("Processing error — will retry")

    return HttpResponse("OK")
