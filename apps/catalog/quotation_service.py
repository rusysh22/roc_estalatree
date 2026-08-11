"""Product quotation PDF — a pre-purchase price quote a visitor can download
from a product detail page (no order/payment required). Mirrors the pattern
in apps/billing/invoice_service.py so there's one PDF-rendering convention.
"""
import io
import logging

logger = logging.getLogger(__name__)


def render_product_quotation_pdf(product, plans) -> bytes | None:
    """Render a price-quote PDF for a product and its currently offered plans.

    Returns None (never raises) — callers decide whether a missing PDF should
    404 or fall back to something else.
    """
    from django.template.loader import render_to_string
    from django.utils import timezone
    from xhtml2pdf import pisa

    from apps.core.branding import base_branding_context

    try:
        context = {
            **base_branding_context(),
            "product": product,
            "plans": plans,
            "generated_at": timezone.now(),
        }
        html = render_to_string("storefront/product_quotation_pdf.html", context)
        buf = io.BytesIO()
        result = pisa.CreatePDF(html, dest=buf)
        if result.err:
            logger.error(
                "render_product_quotation_pdf: xhtml2pdf reported errors for product %s",
                product.slug,
            )
            return None
        return buf.getvalue()
    except Exception:
        logger.exception("render_product_quotation_pdf: failed for product %s", product.slug)
        return None
