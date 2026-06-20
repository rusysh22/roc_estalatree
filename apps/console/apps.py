from django.apps import AppConfig


class OperatorConsoleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.console"
    verbose_name = "Operator Console"

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(_create_operator_group, sender=self)


def _create_operator_group(sender, **kwargs):
    """Ensure the 'Operator' group exists after every migrate."""
    from django.contrib.auth.models import Group
    Group.objects.get_or_create(name="Operator")
