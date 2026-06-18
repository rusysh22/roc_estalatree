"""Concrete provisioners for Phase 4 deliverable types.

Each provisioner creates a Grant record. No external calls in this phase.
Registered in ProvisioningConfig.ready().
"""
import logging

from apps.provisioning.models import Deliverable, Grant

logger = logging.getLogger(__name__)


class ManualProvisioner:
    """Provisioner for manual deliverables — operator fulfills outside the system."""

    def provision(self, order, deliverable) -> Grant:
        return Grant.objects.create(
            customer=order.customer,
            deliverable=deliverable,
            type=Deliverable.Type.MANUAL,
            status=Grant.Status.ACTIVE,
            payload={},
        )

    def renew(self, grant) -> None:
        pass

    def suspend(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.SUSPENDED)

    def resume(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)

    def revoke(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.REVOKED)


class DownloadProvisioner:
    """Provisioner for download links. Config: {"download_url": "..."}"""

    def provision(self, order, deliverable) -> Grant:
        config = deliverable.config or {}
        return Grant.objects.create(
            customer=order.customer,
            deliverable=deliverable,
            type=Deliverable.Type.DOWNLOAD,
            status=Grant.Status.ACTIVE,
            payload={"download_url": config.get("download_url", "")},
        )

    def renew(self, grant) -> None:
        pass

    def suspend(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.SUSPENDED)

    def resume(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)

    def revoke(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.REVOKED)


class AccessLinkProvisioner:
    """Provisioner for time-limited access links. Config: {"access_url": "..."}"""

    def provision(self, order, deliverable) -> Grant:
        config = deliverable.config or {}
        return Grant.objects.create(
            customer=order.customer,
            deliverable=deliverable,
            type=Deliverable.Type.ACCESS_LINK,
            status=Grant.Status.ACTIVE,
            payload={"access_url": config.get("access_url", "")},
        )

    def renew(self, grant) -> None:
        pass

    def suspend(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.SUSPENDED)

    def resume(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)

    def revoke(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.REVOKED)
