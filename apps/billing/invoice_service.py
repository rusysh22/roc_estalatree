"""Invoice PDF generation — shared by the order-confirmation email attachment
and the dashboard's on-demand "Download PDF" button, so there's exactly one
invoice design (docs/feedback: "redesign the invoice PDF, make it detailed").
"""
import io
import logging

logger = logging.getLogger(__name__)


def render_invoice_pdf(order, grants=None) -> bytes | None:
    """Render the paid-invoice PDF for an order. Returns None (never raises) —
    callers decide whether a missing PDF should block anything (it shouldn't
    block the confirmation email, and the dashboard view 404s instead).
    """
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa

    from apps.core.branding import base_branding_context
    from apps.provisioning.models import Grant

    try:
        if grants is None:
            grants = list(Grant.objects.filter(order=order))
        context = {
            **base_branding_context(),
            "order": order,
            "grants": grants,
        }
        html = render_to_string("emails/invoice_pdf.html", context)
        buf = io.BytesIO()
        result = pisa.CreatePDF(html, dest=buf)
        if result.err:
            logger.error("render_invoice_pdf: xhtml2pdf reported errors for order %s", order.public_id)
            return None
        return buf.getvalue()
    except Exception:
        logger.exception("render_invoice_pdf: failed for order %s", order.public_id)
        return None
