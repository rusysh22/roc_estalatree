"""Billing views — payment gateway webhook receivers."""
import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseServerError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing.services import process_webhook_payload

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def duitku_webhook(request):
    """Receive and process Duitku payment callbacks.

    - Returns 200 "OK" on success or non-success result (Duitku stops retrying).
    - Returns 400 on invalid signature (definitively rejected).
    - Returns 500 on unexpected errors so Duitku retries.
    """
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest("Invalid JSON payload")

    merchant_order_id = str(payload.get("merchantOrderId", ""))
    idempotency_key = f"duitku:{merchant_order_id}"

    try:
        process_webhook_payload("duitku", idempotency_key, payload)
    except ValueError as exc:
        logger.warning("Duitku webhook rejected: %s", exc)
        return HttpResponseBadRequest(str(exc))
    except Exception as exc:
        logger.exception("Duitku webhook processing error for %s: %s", merchant_order_id, exc)
        return HttpResponseServerError("Internal error — will retry")

    return HttpResponse("OK")
