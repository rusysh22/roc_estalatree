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


def _uses_wa(customer) -> bool:
    from apps.core.models import NotificationChannel
    return customer.resolve_channel() == NotificationChannel.WHATSAPP


def _notify(customer, *, wa_text: str, email_subject: str, email_body: str) -> None:
    """Send one notification on the customer's chosen channel."""
    from apps.notifications.tasks import deliver_email, deliver_whatsapp
    from apps.notifications.whatsapp import normalize_number

    if _uses_wa(customer):
        deliver_whatsapp.delay(normalize_number(customer.wa_number), wa_text)
    else:
        deliver_email.delay(customer.user.email, email_subject, email_body)


def _wa_copy(customer, wa_text: str) -> None:
    """Push a WhatsApp copy of a value-document notification, only when WA is chosen.

    The authoritative document always goes out by email separately.
    """
    if not _uses_wa(customer):
        return
    from apps.notifications.tasks import deliver_whatsapp
    from apps.notifications.whatsapp import normalize_number
    deliver_whatsapp.delay(normalize_number(customer.wa_number), wa_text)


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
        from apps.notifications.tasks import deliver_topup_confirmation_email
        deliver_topup_confirmation_email.delay(c.user.email, amount, bonus, customer_id)
        _wa_copy(c, msg)
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
        from apps.notifications.tasks import deliver_order_confirmation_email
        deliver_order_confirmation_email.delay(c.user.email, order.pk)
        _wa_copy(c, msg)
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
            f"🧾 *Order Diterima — Menunggu Pembayaran*\n\n"
            f"Produk: *{plan_name or order.plan}*\n"
            f"Jumlah: Rp{order.amount:,}\n\n"
            "Selesaikan pembayaran via QRIS penjual. Pesanan akan diproses setelah "
            "penjual mengonfirmasi pembayaran."
        )
        _notify(
            c,
            wa_text=body,
            email_subject=f"Order diterima — menunggu pembayaran: {plan_name or order.plan}",
            email_body=body,
        )

        # Sellers are email-only (ADR-022).
        seller = getattr(order.plan.product, "seller", None)
        seller_user = getattr(seller, "user", None)
        if seller and seller_user:
            from apps.notifications.tasks import deliver_email
            deliver_email.delay(
                seller_user.email,
                f"Pesanan baru — perlu konfirmasi pembayaran: {plan_name or order.plan}",
                (
                    f"Pesanan baru masuk dan menunggu konfirmasi pembayaran.\n\n"
                    f"Produk: {plan_name or order.plan}\n"
                    f"Jumlah: Rp{order.amount:,}\n\n"
                    "Cek mutasi QRIS Anda, lalu konfirmasi di Seller Dashboard → Orders."
                ),
            )
    except Exception:
        logger.exception("handle_order_awaiting_confirmation: error for order %s", order_id)


@on("order.payment_rejected")
def handle_order_payment_rejected(customer_id, order_id, plan_name="", reason="", **kwargs):
    try:
        c = _customer(customer_id)
        tail = f"\nCatatan penjual: {reason}" if reason else ""
        body = (
            f"⚠️ *Pembayaran Tidak Terverifikasi*\n\n"
            f"Penjual belum menerima pembayaran untuk *{plan_name}*, jadi pesanan dibatalkan."
            f"{tail}\n\nHubungi penjual jika Anda sudah membayar."
        )
        _notify(c, wa_text=body,
                email_subject=f"Pembayaran tidak terverifikasi: {plan_name}", email_body=body)
    except Exception:
        logger.exception("handle_order_payment_rejected: error for customer %s", customer_id)


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
        _notify(c, wa_text=msg,
                email_subject=f"Langganan diperpanjang: {plan_name}", email_body=msg)
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
        _notify(c, wa_text=msg,
                email_subject=f"Perpanjangan gagal: {plan_name}", email_body=msg)
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
        _notify(c, wa_text=msg,
                email_subject=f"Akses ditangguhkan: {plan_name}", email_body=msg)
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
        _notify(c, wa_text=msg,
                email_subject=f"Langganan berakhir: {plan_name}", email_body=msg)
    except Exception:
        logger.exception("handle_subscription_cancelled: error for customer %s", customer_id)
