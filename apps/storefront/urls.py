"""Storefront URL patterns — public-facing: link-in-bio, product pages, checkout."""
from django.urls import path

from apps.storefront import views

app_name = "storefront"

urlpatterns = [
    path("", views.page, name="page"),
    path("p/<slug:slug>/", views.product_detail, name="product"),
    path("checkout/<int:plan_pk>/", views.checkout_plan, name="checkout"),
    path("orders/<public_id>/", views.order_status, name="order_status"),
    path("topup/", views.topup, name="topup"),
    path("contact/<int:product_pk>/", views.contact, name="contact"),
    path("<slug:slug>/", views.page, name="store_page"),
]
