"""ADR-022 — replace additive notif_wa/notif_email booleans with a single
notification_channel choice, plus WhatsApp verification + promo opt-in.

Data migration:
  * notif_wa=True AND notif_email=False  -> "whatsapp" (only if wa_number is set)
  * everything else                      -> "email"
  * wa_number is normalized (081x -> 6281x); invalid numbers are cleared.
  * wa_number_verified_at stays NULL for every existing row, so anyone mapped
    to "whatsapp" effectively falls back to email until they re-verify.
"""
import re

import apps.core.validators
from apps.core.validators import normalize_wa_number
from django.db import migrations, models


def forwards(apps, schema_editor):
    Customer = apps.get_model("accounts", "Customer")
    normalize = normalize_wa_number

    for c in Customer.objects.all().iterator():
        updates = {}

        raw = c.wa_number or ""
        number = normalize(raw)
        if number and not re.fullmatch(r"62\d{8,13}", number):
            number = ""  # drop unparseable legacy values
        if number != raw:
            c.wa_number = number
            updates["wa_number"] = number

        wants_wa = bool(c.notif_wa) and not bool(c.notif_email) and bool(number)
        channel = "whatsapp" if wants_wa else "email"
        if c.notification_channel != channel:
            c.notification_channel = channel
            updates["notification_channel"] = channel

        if updates:
            c.save(update_fields=list(updates))


def backwards(apps, schema_editor):
    Customer = apps.get_model("accounts", "Customer")
    for c in Customer.objects.all().iterator():
        wa = c.notification_channel == "whatsapp"
        c.notif_wa = True  # both defaulted True originally
        c.notif_email = not wa
        c.save(update_fields=["notif_wa", "notif_email"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_sellerprofile_qris_enabled_sellerprofile_qris_image_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="notif_promo",
            field=models.BooleanField(
                default=False,
                help_text="Explicit opt-in for promotional messages (separate from transactional).",
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="notification_channel",
            field=models.CharField(
                choices=[("email", "Email"), ("whatsapp", "WhatsApp")],
                default="email",
                help_text="Preferred channel. WhatsApp only takes effect once the number is verified.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="wa_number_verified_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Set when the number passes OTP verification; cleared when the number changes.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="customer",
            name="wa_number",
            field=models.CharField(
                blank=True, max_length=20, validators=[apps.core.validators.validate_wa_number]
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="customer", name="notif_email"),
        migrations.RemoveField(model_name="customer", name="notif_wa"),
    ]
