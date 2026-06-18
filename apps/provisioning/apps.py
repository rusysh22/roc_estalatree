from django.apps import AppConfig


class ProvisioningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.provisioning"
    verbose_name = "Provisioning"

    def ready(self):
        from apps.provisioning import provisioners, registry

        registry.register("manual", provisioners.ManualProvisioner())
        registry.register("download", provisioners.DownloadProvisioner())
        registry.register("access_link", provisioners.AccessLinkProvisioner())
