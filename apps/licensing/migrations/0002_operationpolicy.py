import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_plan_direct_pay"),
        ("licensing", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("operation", models.SlugField(max_length=100)),
                ("entitlement_key", models.CharField(max_length=100)),
                ("required_value", models.CharField(default="true", max_length=200)),
                ("token_ttl_seconds", models.PositiveIntegerField(default=300)),
                ("is_active", models.BooleanField(default=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operation_policies", to="catalog.product")),
            ],
            options={"ordering": ["product__slug", "operation"]},
        ),
        migrations.AddConstraint(
            model_name="operationpolicy",
            constraint=models.UniqueConstraint(fields=("product", "operation"), name="unique_operation_policy_per_product"),
        ),
    ]
