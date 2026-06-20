"""Concrete provisioners for Phase 4 deliverable types.

Each provisioner creates a Grant record. No external calls in this phase.
Registered in ProvisioningConfig.ready().

H2 (review): Grant.order and Grant.subscription are set so lifecycle cascades
(Phase 6) can find all grants for a given Order or Subscription.
"""
import logging

from apps.provisioning.models import Deliverable, Grant

logger = logging.getLogger(__name__)


class ManualProvisioner:
    """Provisioner for manual deliverables — operator fulfills outside the system."""

    def provision(self, order, deliverable, *, subscription=None) -> Grant:
        return Grant.objects.create(
            customer=order.customer,
            order=order,
            subscription=subscription,
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

    def provision(self, order, deliverable, *, subscription=None) -> Grant:
        config = deliverable.config or {}
        return Grant.objects.create(
            customer=order.customer,
            order=order,
            subscription=subscription,
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

    def provision(self, order, deliverable, *, subscription=None) -> Grant:
        config = deliverable.config or {}
        return Grant.objects.create(
            customer=order.customer,
            order=order,
            subscription=subscription,
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


class CredentialsProvisioner:
    """Provisioner for username/password credentials.

    Config: {"username": "...", "password": "..."}
    Sensitive values are encrypted via the Secret model; Grant.payload stores
    only the reference {"secret_id": pk, "username": "..."} — no plaintext.
    """

    def provision(self, order, deliverable, *, subscription=None) -> Grant:
        from apps.provisioning.crypto import encrypt
        from apps.provisioning.models import Secret

        config = deliverable.config or {}
        username = config.get("username", "")
        password = config.get("password", "")

        grant = Grant.objects.create(
            customer=order.customer,
            order=order,
            subscription=subscription,
            deliverable=deliverable,
            type=Deliverable.Type.CREDENTIALS,
            status=Grant.Status.ACTIVE,
            payload={"username": username},  # password is NOT stored here
        )
        # Encrypt the full credential bundle and store via Secret
        import json
        plaintext = json.dumps({"username": username, "password": password})
        Secret.objects.create(grant=grant, ciphertext=encrypt(plaintext))
        return grant

    def renew(self, grant) -> None:
        pass

    def suspend(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.SUSPENDED)

    def resume(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)

    def revoke(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.REVOKED)


class ApiKeyProvisioner:
    """Provisioner for API key delivery.

    Config: {"api_key": "sk-..."}
    The key is encrypted via the Secret model; Grant.payload is empty.
    """

    def provision(self, order, deliverable, *, subscription=None) -> Grant:
        from apps.provisioning.crypto import encrypt
        from apps.provisioning.models import Secret

        config = deliverable.config or {}
        api_key = config.get("api_key", "")

        grant = Grant.objects.create(
            customer=order.customer,
            order=order,
            subscription=subscription,
            deliverable=deliverable,
            type=Deliverable.Type.API_KEY,
            status=Grant.Status.ACTIVE,
            payload={},  # key is NOT stored here
        )
        Secret.objects.create(grant=grant, ciphertext=encrypt(api_key))
        return grant

    def renew(self, grant) -> None:
        pass

    def suspend(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.SUSPENDED)

    def resume(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)

    def revoke(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.REVOKED)


class CourseProvisioner:
    """Grants access to all lessons in the course product. Config: not required."""

    def provision(self, order, deliverable, *, subscription=None) -> Grant:
        product = deliverable.plan.product
        return Grant.objects.create(
            customer=order.customer,
            order=order,
            subscription=subscription,
            deliverable=deliverable,
            type=Deliverable.Type.COURSE,
            status=Grant.Status.ACTIVE,
            payload={"product_id": product.pk, "product_name": product.name},
        )

    def renew(self, grant) -> None:
        pass

    def suspend(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.SUSPENDED)

    def resume(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)

    def revoke(self, grant) -> None:
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.REVOKED)
