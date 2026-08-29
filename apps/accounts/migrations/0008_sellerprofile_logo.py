from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_customer_notification_channel"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="sellerprofile",
            name="logo_url",
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="seller/logo/"),
        ),
    ]
