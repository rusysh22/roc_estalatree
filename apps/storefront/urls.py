"""Storefront URL patterns — public-facing: link-in-bio, product pages, checkout."""
from django.urls import path

from apps.storefront import views

app_name = "storefront"

urlpatterns = [
    path("", views.landing, name="page"),
    path("p/<slug:slug>/", views.product_detail, name="product"),
    path("p/<slug:slug>/quotation/pdf/", views.product_quotation_pdf, name="product_quotation_pdf"),
    path("qris/<slug:slug>.png", views.qris_download, name="qris_download"),
    path("checkout/<int:plan_pk>/", views.checkout_plan, name="checkout"),
    path("orders/pending/", views.order_pending, name="order_pending"),
    path("orders/<public_id>/invoice.pdf", views.order_invoice_pdf, name="order_invoice_pdf"),
    path("orders/<public_id>/", views.order_status, name="order_status"),
    path("topup/", views.topup, name="topup"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/drawer/", views.cart_drawer, name="cart_drawer"),
    path("cart/add/<int:plan_pk>/", views.cart_add, name="cart_add"),
    path("cart/remove/<int:item_pk>/", views.cart_remove, name="cart_remove"),
    path("cart/update/<int:item_pk>/", views.cart_update, name="cart_update"),
    path("cart/checkout/", views.cart_checkout_view, name="cart_checkout"),
    path("cart/checkout/<public_id>/", views.cart_checkout_receipt, name="cart_checkout_receipt"),
    path("contact/<int:product_pk>/", views.contact, name="contact"),
    path("search/", views.search, name="search"),
    path("legal/", views.legal_index, name="legal_index"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("refunds/", views.refunds, name="refunds"),
    path("purchase-agreement/", views.purchase_agreement, name="purchase_agreement"),
    path("acceptable-use/", views.acceptable_use, name="acceptable_use"),
    path("seller-agreement/", views.seller_agreement, name="seller_agreement"),
    path("cookies/", views.cookies, name="cookies"),
    path("<slug:slug>/", views.page, name="store_page"),
]
