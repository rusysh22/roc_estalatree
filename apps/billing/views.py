"""Billing views — payment gateway webhook receivers."""
import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseServerError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing.services import TopUpNotFoundError, process_webhook_payload

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def duitku_webhook(request):
    """Receive and process Duitku payment callbacks.

    Idempotency key = duitku:<merchantOrderId>:<resultCode> (M2) — ensures a
    non-success callback followed by a success callback for the same order are
    treated as distinct events; the success callback is always processed.

    HTTP response strategy:
    - 200 "OK"  → success or known non-success result (Duitku stops retrying)
    - 400       → invalid signature (definitively bad; no retry needed)
    - 500       → unexpected error or TopUp not found (Duitku retries — safe)
    """
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest("Invalid JSON payload")

    merchant_order_id = str(payload.get("merchantOrderId", ""))
    result_code = str(payload.get("resultCode", ""))
    # M2: include resultCode so a later success callback isn't deduped against
    # an earlier non-success one for the same order.
    idempotency_key = f"duitku:{merchant_order_id}:{result_code}"

    try:
        process_webhook_payload("duitku", idempotency_key, payload)
    except ValueError as exc:
        logger.warning("Duitku webhook rejected (bad request): %s", exc)
        return HttpResponseBadRequest(str(exc))
    except TopUpNotFoundError as exc:
        # M3: let Duitku retry — order may not exist yet due to replication lag.
        logger.error("Duitku webhook TopUp not found: %s", exc)
        return HttpResponseServerError("Order not found — retry")
    except Exception as exc:
        logger.exception("Duitku webhook processing error for %s: %s", merchant_order_id, exc)
        return HttpResponseServerError("Internal error — will retry")

    return HttpResponse("OK")
