from django.urls import path

from apps.notifications import views

app_name = "notifications"

urlpatterns = [
    path("webhook/kirimchat/", views.kirimchat_webhook, name="kirimchat_webhook"),
]
