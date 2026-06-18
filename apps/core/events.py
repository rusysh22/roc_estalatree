"""Domain event bus — lightweight publish/subscribe for cross-app extensibility.

Usage:
    # publish
    from apps.core.events import emit
    emit("order.paid", order_id=order.pk, customer_id=order.customer_id)

    # subscribe (typically in apps.py ready() or a signals module)
    from apps.core.events import on
    @on("order.paid")
    def send_receipt(order_id, **kwargs):
        ...

Cross-app reactions go through events. Never import models across apps directly
in business logic — call a service function or emit an event instead.
"""
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable]] = defaultdict(list)


def on(event_name: str) -> Callable:
    """Decorator to register a handler for a domain event."""

    def decorator(fn: Callable) -> Callable:
        _handlers[event_name].append(fn)
        return fn

    return decorator


def emit(event_name: str, **payload) -> None:
    """Emit a domain event synchronously. Handlers are called in registration order.

    For heavy work (emails, webhooks) the handler should enqueue a Celery task
    rather than doing the work inline.
    """
    for handler in _handlers.get(event_name, []):
        try:
            handler(**payload)
        except Exception:
            logger.exception("Event handler error: event=%s handler=%s", event_name, handler)
