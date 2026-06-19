"""Operator Console views — /console/ (staff/superuser only).

10a  setup          — first-run checklist
10b  cockpit        — KPI cards + unified work queue
10c  customer_list  — search customers
     customer_360   — per-customer detail + actions
     manual_credit  — manual wallet adjustment (superuser-only)
     extend_sub     — extend subscription period + cascade resume
10d  lead_detail    — view/update a CRM lead (staff)
     refund_detail  — view refund (superuser-only)
     refund_approve — approve refund → wallet credit (superuser-only)
     refund_reject  — reject refund (superuser-only)
     export_csv     — CSV download (orders / topups / ledger)
10e  audit_log_view — filterable AuditLog view
     settings_view  — global settings + panic controls
"""
import csv
import os
import uuid

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.console.decorators import staff_required, superuser_required
from apps.core.audit import log_action
from apps.core.models import AuditLog, Setting

# ── Canonical Setting key registry (H1) ──────────────────────────────────────
# These match exactly what the services read. Never invent new names here.
# Source of truth: apps/licensing/services.py + apps/billing/subscription_service.py
_SETTING_KEYS = [
    ("ACTIVATION_TOKEN_TTL_DAYS",   "License token TTL (days)",                  "7"),
    ("ACTIVATION_GRACE_DAYS",       "Licensing grace days before suspension",     "3"),
    ("SUBSCRIPTION_GRACE_DAYS",     "Subscription grace days before suspension",  "3"),
    ("GLOBAL_GRACE_EXTENSION_DAYS", "Global grace extension during incidents (days, 0=off)", "0"),
    ("MAINTENANCE_MODE",            "Maintenance mode — always returns active (true/false)", "false"),
    ("RENEWAL_ADVANCE_HOURS",       "Hours before period_end to run renewal job", "3"),
    ("MIN_TOPUP",                   "Minimum top-up (Rp)",                        "10000"),
    ("MAX_TOPUP",                   "Maximum top-up (Rp)",                        "50000000"),
    ("TOPUP_BONUS_PERCENT",         "Top-up bonus percent (0 = disabled)",        "0"),
    ("SUPPORT_WA_NUMBER",           "Support WhatsApp number (with country code)", ""),
    ("INVOICE_NAME",                "Merchant display name for invoices",          ""),
    ("TAX_ID",                      "Merchant tax ID for invoices",               ""),
]


# ── 10a — First-run setup ─────────────────────────────────────────────────────

@superuser_required
def setup(request):
    from apps.catalog.models import Product
    from apps.storefront.models import StorePage

    checks = [
        ("DUITKU_API_KEY env",           bool(os.environ.get("DUITKU_API_KEY"))),
        ("DUITKU_MERCHANT_CODE env",     bool(os.environ.get("DUITKU_MERCHANT_CODE"))),
        ("WA_TOKEN env",                 bool(os.environ.get("WA_TOKEN"))),
        ("ACTIVATION_TOKEN_TTL_DAYS",    bool(Setting.get("ACTIVATION_TOKEN_TTL_DAYS"))),
        ("ACTIVATION_GRACE_DAYS",        bool(Setting.get("ACTIVATION_GRACE_DAYS"))),
        ("MIN_TOPUP setting",            bool(Setting.get("MIN_TOPUP"))),
        ("StorePage created",            StorePage.objects.exists()),
        ("Product published",            Product.objects.filter(visibility=Product.Visibility.PUBLIC).exists()),
    ]
    all_done = all(ok for _, ok in checks)

    return render(request, "console/setup.html", {
        "checks": checks,
        "all_done": all_done,
    })


# ── 10b — Cockpit ─────────────────────────────────────────────────────────────

@staff_required
def cockpit(request):
    from apps.billing.models import Order, Subscription, TopUp
    from apps.crm.models import Lead
    from apps.dashboard.models import RefundRequest
    from apps.wallet.models import Wallet

    now = timezone.now()
    week_ago = now - timezone.timedelta(days=7)
    two_hours_ago = now - timezone.timedelta(hours=2)

    # Revenue = paid orders not yet refunded (M3: REFUNDED orders excluded by status)
    kpi = {
        "balance_liability": Wallet.objects.aggregate(t=Sum("balance"))["t"] or 0,
        "revenue": Order.objects.filter(status=Order.Status.PAID).aggregate(t=Sum("amount"))["t"] or 0,
        "active_grants": _active_grant_count(),
        "failed_renewals": Subscription.objects.filter(
            status__in=[Subscription.Status.GRACE, Subscription.Status.SUSPENDED]
        ).count(),
        "pending_topups": TopUp.objects.filter(status=TopUp.Status.PENDING).count(),
        "new_orders_7d": Order.objects.filter(status=Order.Status.PAID, created_at__gte=week_ago).count(),
        "open_leads": Lead.objects.filter(status=Lead.Status.NEW).count(),
        "open_refunds": RefundRequest.objects.filter(status=RefundRequest.Status.PENDING).count(),
    }

    # Unified work queue — all items stay in /console/ (H2: no /admin/ links for staff)
    queue = []

    for lead in Lead.objects.filter(status=Lead.Status.NEW).select_related("product")[:20]:
        queue.append({
            "type": "lead",
            "label": f"{lead.name} — {lead.product or 'No product'}",
            "sub": lead.contact,
            "url": f"/console/leads/{lead.pk}/",
            "created_at": lead.created_at,
        })

    for ref in RefundRequest.objects.filter(
        status=RefundRequest.Status.PENDING
    ).select_related("customer", "order")[:20]:
        queue.append({
            "type": "refund",
            "label": f"Refund #{ref.pk} — {ref.customer}",
            "sub": ref.reason[:80],
            "url": f"/console/refund/{ref.pk}/",
            "created_at": ref.created_at,
        })

    for topup in TopUp.objects.filter(
        status=TopUp.Status.PENDING, created_at__lt=two_hours_ago
    ).select_related("customer")[:20]:
        queue.append({
            "type": "stuck_topup",
            "label": f"Stuck top-up {topup.public_id}",
            "sub": f"Rp{topup.amount:,} — {topup.customer}",
            "url": f"/console/customers/{topup.customer_id}/",  # customer 360, no /admin/
            "created_at": topup.created_at,
        })

    for sub in Subscription.objects.filter(
        status__in=[Subscription.Status.GRACE, Subscription.Status.SUSPENDED]
    ).select_related("customer", "plan")[:20]:
        queue.append({
            "type": "renewal",
            "label": f"{sub.customer} — {sub.plan}",
            "sub": f"Status: {sub.get_status_display()}",
            "url": f"/console/customers/{sub.customer_id}/",
            "created_at": sub.created_at,
        })

    queue.sort(key=lambda x: x["created_at"], reverse=True)

    return render(request, "console/cockpit.html", {
        "kpi": kpi,
        "queue": queue[:50],
    })


def _active_grant_count():
    from apps.provisioning.models import Grant
    return Grant.objects.filter(status=Grant.Status.ACTIVE).count()


# ── 10c — Customer 360 ────────────────────────────────────────────────────────

@staff_required
def customer_list(request):
    from apps.accounts.models import Customer

    q = request.GET.get("q", "").strip()
    customers = Customer.objects.select_related("user", "wallet").order_by("-created_at")
    if q:
        customers = customers.filter(user__email__icontains=q)

    return render(request, "console/customer_list.html", {
        "customers": customers[:100],
        "q": q,
    })


@staff_required
def customer_360(request, customer_pk):
    from apps.accounts.models import Customer
    from apps.billing.models import Order, Subscription
    from apps.dashboard.models import RefundRequest
    from apps.licensing.models import Installation
    from apps.provisioning.models import Grant
    from apps.wallet.models import LedgerEntry

    customer = get_object_or_404(Customer, pk=customer_pk)

    orders = Order.objects.filter(customer=customer).select_related("plan").order_by("-created_at")[:20]
    ledger = LedgerEntry.objects.filter(wallet=customer.wallet).order_by("-created_at")[:30]
    grants = Grant.objects.filter(customer=customer).select_related("deliverable__plan").order_by("-created_at")[:20]
    subs = Subscription.objects.filter(customer=customer).select_related("plan").order_by("-created_at")
    refunds = RefundRequest.objects.filter(customer=customer).order_by("-created_at")[:10]
    # M4: target_type matches type(target).__name__ = "Customer" (capitalised)
    audit = AuditLog.objects.filter(
        target_type="Customer", target_id=str(customer.pk)
    ).order_by("-created_at")[:30]

    try:
        installations = Installation.objects.filter(
            license__customer=customer
        ).select_related("license__product").order_by("-created_at")[:20]
    except Exception:
        installations = []

    return render(request, "console/customer_360.html", {
        "customer": customer,
        "orders": orders,
        "ledger": ledger,
        "grants": grants,
        "subs": subs,
        "refunds": refunds,
        "audit": audit,
        "installations": installations,
    })


@superuser_required  # H2: balance adjustment is superuser-only
@require_POST
def manual_credit(request, customer_pk):
    from apps.accounts.models import Customer
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import credit

    customer = get_object_or_404(Customer, pk=customer_pk)

    try:
        amount = int(request.POST.get("amount", 0))
        reason = request.POST.get("reason", "").strip()
    except (ValueError, TypeError):
        amount = 0
        reason = ""

    if amount <= 0 or not reason:
        messages.error(request, "Amount and reason are required.")
        return redirect("console:customer_360", customer_pk=customer_pk)

    ref = f"adj:{uuid.uuid4().hex[:16]}"
    with transaction.atomic():
        credit(
            wallet=customer.wallet,
            amount=amount,
            entry_type=LedgerEntry.Type.ADJUSTMENT,
            ref=ref,
            note=f"Manual credit by {request.user.email}: {reason}",
        )
        log_action(
            "wallet.manual_credit",
            actor=request.user,
            target=customer,
            meta={"amount": amount, "reason": reason, "ref": ref},
        )

    messages.success(request, f"Credited Rp{amount:,} to {customer}.")
    return redirect("console:customer_360", customer_pk=customer_pk)


@staff_required
@require_POST
def extend_subscription(request, sub_pk):
    from apps.billing.models import Subscription
    from apps.provisioning.models import Grant
    from apps.provisioning.registry import get as get_provisioner

    sub = get_object_or_404(Subscription, pk=sub_pk)

    try:
        days = int(request.POST.get("days", 0))
    except (ValueError, TypeError):
        days = 0

    if days <= 0 or days > 365:
        messages.error(request, "Days must be between 1 and 365.")
        return redirect("console:customer_360", customer_pk=sub.customer_id)

    with transaction.atomic():
        was_suspended = sub.status == Subscription.Status.SUSPENDED
        sub.current_period_end += timezone.timedelta(days=days)
        if was_suspended:
            sub.status = Subscription.Status.ACTIVE
        sub.save(update_fields=["current_period_end", "status", "updated_at"])

        # M2: cascade resume to all suspended grants for this subscription
        if was_suspended:
            for grant in Grant.objects.filter(subscription=sub, status=Grant.Status.SUSPENDED):
                try:
                    get_provisioner(grant.type).resume(grant)
                except (KeyError, Exception):
                    pass  # unregistered type; skip silently

        log_action(
            "subscription.extended",
            actor=request.user,
            target=sub,
            meta={"days": days, "new_period_end": sub.current_period_end.isoformat()},
        )

    messages.success(request, f"Subscription extended by {days} day(s).")
    return redirect("console:customer_360", customer_pk=sub.customer_id)


# ── 10c — Lead detail (staff action, no /admin/ needed) ──────────────────────

@staff_required
def lead_detail(request, pk):
    from apps.crm.models import Lead

    lead = get_object_or_404(Lead, pk=pk)

    if request.method == "POST":
        new_status = request.POST.get("status", "").strip()
        notes = request.POST.get("notes", "").strip()
        valid_statuses = [s for s, _ in Lead.Status.choices]
        if new_status in valid_statuses:
            lead.status = new_status
            lead.notes = notes
            lead.assigned_to = request.user
            lead.save(update_fields=["status", "notes", "assigned_to", "updated_at"])
            log_action("lead.updated", actor=request.user, target=lead, meta={"status": new_status})
            messages.success(request, f"Lead #{lead.pk} updated.")
            return redirect("console:cockpit")
        messages.error(request, "Invalid status.")

    return render(request, "console/lead_detail.html", {"lead": lead})


# ── 10d — Refund queue (superuser-only — H2) ──────────────────────────────────

@superuser_required  # H2: refund actions are superuser-only
def refund_detail(request, pk):
    from apps.dashboard.models import RefundRequest

    ref = get_object_or_404(RefundRequest, pk=pk)
    return render(request, "console/refund_detail.html", {"ref": ref})


@superuser_required  # H2
@require_POST
def refund_approve(request, pk):
    from apps.billing.models import Order
    from apps.dashboard.models import RefundRequest
    from apps.wallet.models import LedgerEntry
    from apps.wallet.services import credit

    # H3: lock the row first, then re-check status inside the transaction
    with transaction.atomic():
        ref = RefundRequest.objects.select_for_update().get(pk=pk)
        if ref.status != RefundRequest.Status.PENDING:
            messages.error(request, "Refund is no longer pending.")
            return redirect("console:refund_detail", pk=pk)

        amount = ref.order.amount if ref.order else 0
        if amount <= 0:
            messages.error(request, "Cannot approve: no linked order amount.")
            return redirect("console:refund_detail", pk=pk)

        # H3: deterministic ref so credit() deduplicates on double-submit
        refund_ref = f"refund:{ref.pk}"
        credit(
            wallet=ref.customer.wallet,
            amount=amount,
            entry_type=LedgerEntry.Type.ADJUSTMENT,
            ref=refund_ref,
            note=f"Refund approved by {request.user.email}",
        )

        # M3: mark order REFUNDED so revenue KPI excludes it
        if ref.order:
            ref.order.status = Order.Status.REFUNDED
            ref.order.save(update_fields=["status", "updated_at"])

        ref.status = RefundRequest.Status.APPROVED
        ref.admin_note = request.POST.get("admin_note", "").strip()
        ref.save(update_fields=["status", "admin_note", "updated_at"])
        log_action(
            "refund.approved",
            actor=request.user,
            target=ref,
            meta={"amount": amount, "ref": refund_ref},
        )

    messages.success(request, f"Refund #{ref.pk} approved — Rp{amount:,} credited.")
    return redirect("console:cockpit")


@superuser_required  # H2
@require_POST
def refund_reject(request, pk):
    from apps.dashboard.models import RefundRequest

    admin_note = request.POST.get("admin_note", "").strip()
    if not admin_note:
        messages.error(request, "Rejection reason is required.")
        return redirect("console:refund_detail", pk=pk)

    with transaction.atomic():
        ref = RefundRequest.objects.select_for_update().get(pk=pk)
        if ref.status != RefundRequest.Status.PENDING:
            messages.error(request, "Refund is no longer pending.")
            return redirect("console:refund_detail", pk=pk)

        ref.status = RefundRequest.Status.REJECTED
        ref.admin_note = admin_note
        ref.save(update_fields=["status", "admin_note", "updated_at"])
        log_action("refund.rejected", actor=request.user, target=ref, meta={"admin_note": admin_note})

    messages.success(request, f"Refund #{ref.pk} rejected.")
    return redirect("console:cockpit")


# ── 10d — CSV exports ─────────────────────────────────────────────────────────

@staff_required
def export_csv(request, model_name):
    from apps.billing.models import Order, TopUp
    from apps.wallet.models import LedgerEntry

    allowed = {"orders", "topups", "ledger"}
    if model_name not in allowed:
        return HttpResponse("Not found", status=404)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{model_name}.csv"'
    writer = csv.writer(response)

    if model_name == "orders":
        writer.writerow(["public_id", "customer", "plan", "amount", "status", "created_at"])
        for o in Order.objects.select_related("customer__user", "plan").iterator():
            writer.writerow([o.public_id, o.customer.user.email, str(o.plan), o.amount, o.status, o.created_at.isoformat()])

    elif model_name == "topups":
        writer.writerow(["public_id", "customer", "amount", "bonus", "status", "gateway_ref", "created_at"])
        for t in TopUp.objects.select_related("customer__user").iterator():
            writer.writerow([t.public_id, t.customer.user.email, t.amount, t.bonus, t.status, t.gateway_ref, t.created_at.isoformat()])

    elif model_name == "ledger":
        writer.writerow(["ref", "wallet", "type", "amount", "balance_after", "note", "created_at"])
        for e in LedgerEntry.objects.select_related("wallet__customer__user").iterator():
            email = e.wallet.customer.user.email if hasattr(e.wallet, "customer") else ""
            # M1: field is `type`, not `entry_type`
            writer.writerow([e.ref, email, e.type, e.amount, e.balance_after, e.note, e.created_at.isoformat()])

    log_action("export.csv", actor=request.user, meta={"model": model_name})
    return response


# ── 10e — Audit log ───────────────────────────────────────────────────────────

@staff_required
def audit_log_view(request):
    action_filter = request.GET.get("action", "").strip()
    actor_filter = request.GET.get("actor", "").strip()

    entries = AuditLog.objects.select_related("actor").order_by("-created_at")
    if action_filter:
        entries = entries.filter(action__icontains=action_filter)
    if actor_filter:
        entries = entries.filter(actor__email__icontains=actor_filter)

    return render(request, "console/audit_log.html", {
        "entries": entries[:200],
        "action_filter": action_filter,
        "actor_filter": actor_filter,
    })


# ── 10e — Settings + panic controls ──────────────────────────────────────────

@superuser_required
def settings_view(request):
    if request.method == "POST":
        for key, _, _ in _SETTING_KEYS:
            value = request.POST.get(key, "").strip()
            if value != "":
                obj, _ = Setting.objects.get_or_create(key=key)
                if obj.value != value:
                    old_value = obj.value
                    obj.value = value
                    obj.save(update_fields=["value", "updated_at"])
                    log_action(
                        "setting.changed",
                        actor=request.user,
                        meta={"key": key, "old": old_value, "new": value},
                    )

        messages.success(request, "Settings saved.")
        return redirect("console:settings")

    current = {key: Setting.get(key, default) for key, _, default in _SETTING_KEYS}
    maintenance_on = Setting.get("MAINTENANCE_MODE", "false").strip().lower() == "true"

    return render(request, "console/settings.html", {
        "editable_keys": [(key, label) for key, label, _ in _SETTING_KEYS],
        "current": current,
        "maintenance_on": maintenance_on,
    })
