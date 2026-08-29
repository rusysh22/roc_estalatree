"""Domain event handlers — subscribe to billing/subscription events and
dispatch notification tasks.

All handlers are registered via NotificationsConfig.ready() importing this module.
Handlers fire after transaction.on_commit (emit() contract) — they never observe
rolled-back state. Each handler dispatches Celery tasks; nothing blocks.

Delivery model (ADR-022): each customer has ONE channel (`resolve_channel()`).
`_notify()` sends to that channel only. Value documents (receipts, invoices,
license keys) are always emailed via their dedicated HTML-email tasks; for those
handlers we additionally push a short WhatsApp copy only when WA is the chosen
channel (`_wa_copy()`).

Events and channels:
  topup.paid             → email (HTML receipt) + WA copy if channel=WA
  order.paid             → email (HTML receipt) + WA copy if channel=WA
  order.awaiting_confirmation → buyer: chosen channel · seller: email
  order.payment_rejected → chosen channel
  subscription.renewed / graced / suspended / cancelled → chosen channel
"""
import logging

from apps.core.events import on

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _customer(customer_id):
    from apps.accounts.models import Customer
    return Customer.objects.select_related("user", "wallet").get(pk=customer_id)


def _notify(customer, *, event, wa_text, email_subject, email_body):
    from apps.notifications.dispatch import notify
    notify(customer, event=event, wa_text=wa_text,
           email_subject=email_subject, email_body=email_body)


def _wa_copy(customer, event, wa_text):
    from apps.notifications.dispatch import notify_wa_copy
    notify_wa_copy(customer, event=event, wa_text=wa_text)


# ── Handlers ──────────────────────────────────────────────────────────────────

@on("topup.paid")
def handle_topup_paid(customer_id, amount, bonus=0, **kwargs):
    try:
        c = _customer(customer_id)
        bonus_text = f" + Rp{bonus:,} bonus" if bonus else ""
        msg = (
            f"✅ *Top-up successful*\n\n"
            f"Rp{amount:,}{bonus_text} has been credited to your balance.\n"
            f"Your balance is ready to use for purchases."
        )
        from apps.notifications.tasks import deliver_topup_confirmation_email
        deliver_topup_confirmation_email.delay(c.user.email, amount, bonus, customer_id)
        _wa_copy(c, "topup.paid", msg)
    except Exception:
        logger.exception("handle_topup_paid: error for customer %s", customer_id)


@on("order.paid")
def handle_order_paid(customer_id, order_id, plan_name="", **kwargs):
    try:
        from apps.billing.models import Order
        from apps.provisioning.models import Grant

        c = _customer(customer_id)
        order = Order.objects.get(pk=order_id)
        grants = list(Grant.objects.filter(order=order))

        delivery_lines = []
        for g in grants:
            if g.type == "license_key" and g.payload.get("license_key"):
                delivery_lines.append(f"License Key: `{g.payload['license_key']}`")
            elif g.type == "download" and g.payload.get("download_url"):
                delivery_lines.append(f"Download: {g.payload['download_url']}")
            elif g.type == "access_link" and g.payload.get("access_url"):
                delivery_lines.append(f"Access: {g.payload['access_url']}")
            elif g.type in ("credentials", "api_key"):
                delivery_lines.append("Credentials / API key are available in your product dashboard.")

        if not delivery_lines:
            delivery_lines.append("Your product is ready — check your dashboard for access details.")

        delivery_text = "\n".join(delivery_lines)

        msg = (
            f"\U0001f389 *Purchase successful*\n\n"
            f"Product: *{plan_name or order.plan}*\n\n"
            f"{delivery_text}\n\n"
            "Thank you! Keep this access information safe."
        )
        from apps.notifications.tasks import deliver_order_confirmation_email
        deliver_order_confirmation_email.delay(c.user.email, order.pk)
        _wa_copy(c, "order.paid", msg)
    except Exception:
        logger.exception("handle_order_paid: error for customer %s", customer_id)


@on("order.awaiting_confirmation")
def handle_order_awaiting_confirmation(customer_id, order_id, plan_name="", **kwargs):
    """Tell the buyer their QRIS order is placed, and nudge the seller to confirm."""
    try:
        from apps.billing.models import Order

        order = Order.objects.select_related("plan__product__seller__user").get(pk=order_id)

        c = _customer(customer_id)
        body = (
            f"🧾 *Order received — awaiting payment*\n\n"
            f"Product: *{plan_name or order.plan}*\n"
            f"Amount: Rp{order.amount:,}\n\n"
            "Complete the payment via the seller's QRIS. Your order will be processed "
            "once the seller confirms payment."
        )
        _notify(
            c,
            event="order.awaiting_confirmation",
            wa_text=body,
            email_subject=f"Order received — awaiting payment: {plan_name or order.plan}",
            email_body=body,
        )

        # Sellers are email-only (ADR-022).
        seller = getattr(order.plan.product, "seller", None)
        seller_user = getattr(seller, "user", None)
        if seller and seller_user:
            from apps.notifications.tasks import deliver_email
            deliver_email.delay(
                seller_user.email,
                f"New order — payment confirmation needed: {plan_name or order.plan}",
                (
                    f"A new order has come in and is awaiting payment confirmation.\n\n"
                    f"Product: {plan_name or order.plan}\n"
                    f"Amount: Rp{order.amount:,}\n\n"
                    "Check your QRIS transactions, then confirm in Seller Dashboard → Orders."
                ),
            )
    except Exception:
        logger.exception("handle_order_awaiting_confirmation: error for order %s", order_id)


@on("order.payment_rejected")
def handle_order_payment_rejected(customer_id, order_id, plan_name="", reason="", **kwargs):
    try:
        c = _customer(customer_id)
        tail = f"\nSeller note: {reason}" if reason else ""
        body = (
            f"⚠️ *Payment not verified*\n\n"
            f"The seller has not received payment for *{plan_name}*, so the order was cancelled."
            f"{tail}\n\nContact the seller if you have already paid."
        )
        _notify(c, event="order.payment_rejected", wa_text=body,
                email_subject=f"Payment not verified: {plan_name}", email_body=body)
    except Exception:
        logger.exception("handle_order_payment_rejected: error for customer %s", customer_id)


@on("subscription.renewed")
def handle_subscription_renewed(customer_id, sub_id, plan_name="", new_period_end="", **kwargs):
    try:
        c = _customer(customer_id)
        period_str = new_period_end[:10] if new_period_end else "-"
        msg = (
            f"✅ *Subscription renewed*\n\n"
            f"Your *{plan_name}* subscription has been renewed.\n"
            f"Active until: {period_str}"
        )
        _notify(c, event="subscription.renewed", wa_text=msg,
                email_subject=f"Subscription renewed: {plan_name}", email_body=msg)
    except Exception:
        logger.exception("handle_subscription_renewed: error for customer %s", customer_id)


@on("subscription.graced")
def handle_subscription_graced(customer_id, sub_id, plan_name="", grace_days=3, **kwargs):
    try:
        c = _customer(customer_id)
        msg = (
            f"⚠️ *Renewal failed — grace period active*\n\n"
            f"Your balance was not enough to renew *{plan_name}*.\n"
            f"You still have a {grace_days}-day grace period.\n"
            f"Top up now to keep your access active."
        )
        _notify(c, event="subscription.graced", wa_text=msg,
                email_subject=f"Renewal failed: {plan_name}", email_body=msg)
    except Exception:
        logger.exception("handle_subscription_graced: error for customer %s", customer_id)


@on("subscription.suspended")
def handle_subscription_suspended(customer_id, sub_id, plan_name="", **kwargs):
    try:
        c = _customer(customer_id)
        msg = (
            f"\U0001f512 *Access suspended*\n\n"
            f"Your *{plan_name}* subscription was suspended because your balance was "
            f"insufficient and the grace period has ended.\n"
            f"Top up now — access will be restored automatically."
        )
        _notify(c, event="subscription.suspended", wa_text=msg,
                email_subject=f"Access suspended: {plan_name}", email_body=msg)
    except Exception:
        logger.exception("handle_subscription_suspended: error for customer %s", customer_id)


@on("subscription.cancelled")
def handle_subscription_cancelled(customer_id, sub_id, plan_name="", **kwargs):
    try:
        c = _customer(customer_id)
        msg = (
            f"ℹ️ *Subscription ended*\n\n"
            f"Your *{plan_name}* subscription has ended (auto-renew is off).\n"
            f"Reactivate any time from your dashboard."
        )
        _notify(c, event="subscription.cancelled", wa_text=msg,
                email_subject=f"Subscription ended: {plan_name}", email_body=msg)
    except Exception:
        logger.exception("handle_subscription_cancelled: error for customer %s", customer_id)
