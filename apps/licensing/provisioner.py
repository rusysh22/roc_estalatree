"""LicenseKeyProvisioner — creates License + Grant for license_key deliverables.

Registered in LicensingConfig.ready() alongside the provisioners in provisioning/apps.py.

Lifecycle cascade:
  suspend() → License.SUSPENDED + Grant.SUSPENDED
  resume()  → License.ACTIVE   + Grant.ACTIVE
  revoke()  → License.REVOKED  + Grant.REVOKED
  renew()   → re-activate grant (Phase 6 handles period extension)
"""
import logging

from apps.provisioning.models import Deliverable, Grant

logger = logging.getLogger(__name__)


class LicenseKeyProvisioner:
    """Provision a License + activation-API-ready Grant for license_key deliverables."""

    def provision(self, order, deliverable, *, subscription=None) -> Grant:
        from apps.licensing.models import License

        seat_limit = deliverable.config.get("seat_limit") or order.plan.seat_limit

        # Create License first — key auto-assigned in License.save()
        license = License.objects.create(
            customer=order.customer,
            plan=order.plan,
            subscription=subscription,
            grant=None,
            status=License.Status.ACTIVE,
            seat_limit=seat_limit,
        )

        # Create Grant with license key in payload for API convenience
        grant = Grant.objects.create(
            customer=order.customer,
            order=order,
            subscription=subscription,
            deliverable=deliverable,
            type=Deliverable.Type.LICENSE_KEY,
            status=Grant.Status.ACTIVE,
            payload={"license_key": license.key, "license_id": license.pk},
        )

        # Link Grant ↔ License
        License.objects.filter(pk=license.pk).update(grant=grant)

        logger.info(
            "LicenseKeyProvisioner: provisioned %s for order %s (seat_limit=%d)",
            license.key,
            order.public_id,
            seat_limit,
        )
        return grant

    def renew(self, grant) -> None:
        """Re-activate grant on subscription renewal. Period extension handled by Phase 6."""
        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)
        from apps.licensing.models import License
        License.objects.filter(grant=grant).update(status=License.Status.ACTIVE)
        logger.info("LicenseKeyProvisioner: renewed grant %s", grant.pk)

    def suspend(self, grant) -> None:
        from apps.core.audit import log_action
        from apps.licensing.models import License

        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.SUSPENDED)
        License.objects.filter(grant=grant).update(status=License.Status.SUSPENDED)
        log_action(
            action="license.suspended",
            target=grant,
            meta={"grant_id": grant.pk, "provisioner": "license_key"},
        )
        logger.info("LicenseKeyProvisioner: suspended grant %s", grant.pk)

    def resume(self, grant) -> None:
        from apps.licensing.models import License

        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.ACTIVE)
        License.objects.filter(grant=grant).update(status=License.Status.ACTIVE)
        logger.info("LicenseKeyProvisioner: resumed grant %s", grant.pk)

    def revoke(self, grant) -> None:
        from apps.core.audit import log_action
        from apps.licensing.models import License

        Grant.objects.filter(pk=grant.pk).update(status=Grant.Status.REVOKED)
        License.objects.filter(grant=grant).update(status=License.Status.REVOKED)
        log_action(
            action="license.revoked",
            target=grant,
            meta={"grant_id": grant.pk, "provisioner": "license_key"},
        )
        logger.info("LicenseKeyProvisioner: revoked grant %s", grant.pk)
