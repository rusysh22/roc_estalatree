"""Domain event handlers — subscribe to billing/subscription events and
dispatch notification tasks.

All handlers are registered via NotificationsConfig.ready() importing this module.
Handlers fire after transaction.on_commit (emit() contract) — they never observe
rolled-back state. Each handler dispatches Celery tasks; nothing blocks.

Events and channels:
  topup.paid             → WA + email
  order.paid             → WA + email (with license key if applicable)
  subscription.renewed   → WA
  subscription.graced    → WA + email
  subscription.suspended → WA + email
  subscription.cancelled → WA
"""
import logging

from apps.core.events import on

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _customer(customer_id):
    from apps.accounts.models import Customer
    return Customer.objects.select_related("user", "wallet").get(pk=customer_id)


def _wa(customer, message: str) -> None:
    from apps.notifications.tasks import deliver_whatsapp
    from apps.notifications.whatsapp import normalize_number
    if customer.wa_number:
        deliver_whatsapp.delay(normalize_number(customer.wa_number), message)


def _email(customer, subject: str, message: str) -> None:
    from apps.notifications.tasks import deliver_email
    deliver_email.delay(customer.user.email, subject, message)


# ── Handlers ──────────────────────────────────────────────────────────────────

@on("topup.paid")
def handle_topup_paid(customer_id, amount, bonus=0, **kwargs):
    try:
        c = _customer(customer_id)
        bonus_text = f" + bonus Rp{bonus:,}" if bonus else ""
        msg = (
            f"✅ *Top-up Berhasil*\n\n"
            f"Rp{amount:,}{bonus_text} telah dikreditkan ke saldo Anda.\n"
            f"Saldo siap digunakan untuk pembelian."
        )
        _wa(c, msg)
        _email(c, "Top-up berhasil dikreditkan", msg)
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
                delivery_lines.append(f"Akses: {g.payload['access_url']}")
            elif g.type in ("credentials", "api_key"):
                delivery_lines.append("Kredensial/API Key tersedia di dashboard produk Anda.")

        if not delivery_lines:
            delivery_lines.append("Produk Anda siap — cek dashboard untuk detail akses.")

        delivery_text = "\n".join(delivery_lines)

        msg = (
            f"\U0001f389 *Pembelian Berhasil*\n\n"
            f"Produk: *{plan_name or order.plan}*\n\n"
            f"{delivery_text}\n\n"
            "Terima kasih! Simpan informasi akses ini dengan aman."
        )
        _wa(c, msg)
        _email(c, f"Pembelian berhasil: {plan_name or order.plan}", msg)
    except Exception:
        logger.exception("handle_order_paid: error for customer %s", customer_id)


@on("subscription.renewed")
def handle_subscription_renewed(customer_id, sub_id, plan_name="", new_period_end="", **kwargs):
    try:
        c = _customer(customer_id)
        period_str = new_period_end[:10] if new_period_end else "-"
        msg = (
            f"✅ *Langganan Diperpanjang*\n\n"
            f"Langganan *{plan_name}* berhasil diperpanjang.\n"
            f"Aktif hingga: {period_str}"
        )
        _wa(c, msg)
    except Exception:
        logger.exception("handle_subscription_renewed: error for customer %s", customer_id)


@on("subscription.graced")
def handle_subscription_graced(customer_id, sub_id, plan_name="", grace_days=3, **kwargs):
    try:
        c = _customer(customer_id)
        msg = (
            f"⚠️ *Perpanjangan Gagal — Masa Tenggang Aktif*\n\n"
            f"Saldo tidak cukup untuk memperpanjang *{plan_name}*.\n"
            f"Anda masih punya masa tenggang {grace_days} hari.\n"
            f"Top up sekarang untuk menjaga akses tetap aktif."
        )
        _wa(c, msg)
        _email(c, f"Perpanjangan gagal: {plan_name}", msg)
    except Exception:
        logger.exception("handle_subscription_graced: error for customer %s", customer_id)


@on("subscription.suspended")
def handle_subscription_suspended(customer_id, sub_id, plan_name="", **kwargs):
    try:
        c = _customer(customer_id)
        msg = (
            f"\U0001f512 *Akses Ditangguhkan*\n\n"
            f"Langganan *{plan_name}* ditangguhkan karena saldo tidak mencukupi "
            f"dan masa tenggang telah habis.\n"
            f"Top up sekarang — akses akan aktif kembali otomatis."
        )
        _wa(c, msg)
        _email(c, f"Akses ditangguhkan: {plan_name}", msg)
    except Exception:
        logger.exception("handle_subscription_suspended: error for customer %s", customer_id)


@on("subscription.cancelled")
def handle_subscription_cancelled(customer_id, sub_id, plan_name="", **kwargs):
    try:
        c = _customer(customer_id)
        msg = (
            f"ℹ️ *Langganan Berakhir*\n\n"
            f"Langganan *{plan_name}* telah berakhir (auto-renew tidak aktif).\n"
            f"Aktifkan kembali kapan saja melalui dashboard."
        )
        _wa(c, msg)
    except Exception:
        logger.exception("handle_subscription_cancelled: error for customer %s", customer_id)
