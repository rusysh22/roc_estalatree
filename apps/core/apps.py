from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(sync_site_domain, sender=self)


def sync_site_domain(sender, **kwargs):
    """Keep the django.contrib.sites Site row in sync with SITE_DOMAIN/SITE_NAME.

    Runs after every `migrate` (including no-op runs, since docker-entrypoint.sh
    runs migrate on every deploy) so a changed ALLOWED_HOSTS/SITE_DOMAIN always
    takes effect without a manual admin edit — this is what was still stuck on
    the django.contrib.sites default of "example.com" in production emails.
    sender=self (apps.core's AppConfig) so this only runs once per migrate, not
    once per installed app.
    """
    from django.conf import settings
    from django.contrib.sites.models import Site

    Site.objects.update_or_create(
        pk=settings.SITE_ID,
        defaults={"domain": settings.SITE_DOMAIN, "name": settings.SITE_NAME},
    )
