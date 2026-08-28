"""Billing views — payment gateway webhook receiver (Sumopod)."""
import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseServerError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing.services import TopUpNotFoundError, process_webhook_payload

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def sumopod_webhook(request):
    """Receive and process Sumopod payment webhooks.

    Verification (both enforced when configured):
      - Svix signature: svix-id / svix-timestamp / svix-signature headers, HMAC-SHA256.
      - X-Webhook-Token header compared to SUMOPOD_WEBHOOK_TOKEN.

    Idempotency key = sumopod:<svix-id> — stable across Sumopod's retries of the
    same delivery; falls back to sumopod:<payment_id>:<event_type>.

    HTTP response strategy (Sumopod expects 2xx within 10s):
      - 200 "OK"  → processed, or a known/unhandled event (stop retrying)
      - 400       → unparseable payload
      - 401       → signature/token verification failed
      - 500       → TopUp not found or unexpected error (Sumopod retries — safe)
    """
    from apps.billing.sumopod import SumopodClient, SumopodError

    raw_body = request.body

    try:
        client = SumopodClient.from_settings()
    except SumopodError as exc:
        logger.error("Sumopod webhook: gateway not configured: %s", exc)
        return HttpResponseServerError("Gateway not configured")

    try:
        if not client.verify_webhook(request.headers, raw_body):
            logger.warning("Sumopod webhook rejected: signature/token verification failed")
            return HttpResponse("Invalid signature", status=401)
    except SumopodError as exc:
        logger.error("Sumopod webhook: verification not configured: %s", exc)
        return HttpResponseServerError("Webhook verification not configured")

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest("Invalid or empty payload")

    event_type = str(payload.get("event_type", ""))
    data = payload.get("data") or {}
    svix_id = request.headers.get("svix-id", "")
    if svix_id:
        idempotency_key = f"sumopod:{svix_id}"
    else:
        idempotency_key = f"sumopod:{data.get('payment_id', '')}:{event_type}"

    try:
        process_webhook_payload("sumopod", idempotency_key, payload)
    except ValueError as exc:
        logger.warning("Sumopod webhook rejected (bad request): %s", exc)
        return HttpResponseBadRequest(str(exc))
    except TopUpNotFoundError as exc:
        logger.error("Sumopod webhook TopUp not found: %s", exc)
        return HttpResponseServerError("Order not found — retry")
    except Exception as exc:
        logger.exception("Sumopod webhook processing error (%s): %s", idempotency_key, exc)
        return HttpResponseServerError("Internal error — will retry")

    return HttpResponse("OK")
