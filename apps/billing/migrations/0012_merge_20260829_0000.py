from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0010_order_payment_channel_order_payment_proof"),
        ("billing", "0011_topup_gateway_fee"),
    ]

    operations = []
