"""Domain event bus — lightweight publish/subscribe for cross-app extensibility.

Usage:
    # publish (call inside a transaction — handlers fire after commit)
    from apps.core.events import emit
    emit("order.paid", order_id=order.pk, customer_id=order.customer_id)

    # subscribe (in apps.py ready() or a signals module)
    from apps.core.events import on
    @on("order.paid")
    def send_receipt(order_id, **kwargs):
        ...

H4 (review): handlers are dispatched via transaction.on_commit so they never
observe rolled-back state. This means events are for SIDE-EFFECTS only (emails,
Celery tasks, notifications) — never for money correctness. Money steps stay
inside the calling transaction.

If emit() is called outside a transaction (e.g. in a test or shell), on_commit
fires immediately, which is the correct Django behaviour.
"""
import logging
from collections import defaultdict
from functools import partial
from typing import Callable

from django.db import transaction

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable]] = defaultdict(list)


def on(event_name: str) -> Callable:
    """Decorator to register a handler for a domain event."""

    def decorator(fn: Callable) -> Callable:
        _handlers[event_name].append(fn)
        return fn

    return decorator


def _call_handler(handler: Callable, payload: dict) -> None:
    try:
        handler(**payload)
    except Exception:
        logger.exception("Event handler error: handler=%s", handler)


def emit(event_name: str, **payload) -> None:
    """Emit a domain event. Handlers fire after the current transaction commits.

    Safe to call from inside atomic blocks — handlers never see rolled-back state.
    """
    for handler in _handlers.get(event_name, []):
        transaction.on_commit(partial(_call_handler, handler, payload))