"""Provisioner registry — plugin pattern for fulfillment.

Every sellable deliverable type has a registered Provisioner.
To add a new type: implement the BaseProvisioner interface and call register().

See docs/15-provisioning-and-entitlements.md.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass  # avoid circular imports; use strings for forward refs

_registry: dict[str, "BaseProvisioner"] = {}


@runtime_checkable
class BaseProvisioner(Protocol):
    """Interface every provisioner must satisfy."""

    def provision(self, order, deliverable, *, subscription=None) -> object:
        """Fulfill one deliverable for an order; return a Grant instance."""
        ...

    def renew(self, grant) -> None:
        """Extend the grant validity on subscription renewal."""
        ...

    def suspend(self, grant) -> None:
        """Suspend the grant when a subscription enters grace/suspended state."""
        ...

    def resume(self, grant) -> None:
        """Resume the grant when a subscription is reactivated."""
        ...

    def revoke(self, grant) -> None:
        """Permanently revoke the grant on cancellation/expiry/abuse."""
        ...


def register(deliverable_type: str, provisioner: BaseProvisioner) -> None:
    """Register a provisioner for a deliverable type.

    Args:
        deliverable_type: e.g. "license_key", "credentials", "download".
        provisioner: An instance implementing BaseProvisioner.
    """
    if deliverable_type in _registry:
        raise ValueError(f"Provisioner already registered for type: {deliverable_type!r}")
    _registry[deliverable_type] = provisioner


def get(deliverable_type: str) -> BaseProvisioner:
    """Retrieve the provisioner for a deliverable type.

    Raises:
        KeyError: if no provisioner is registered for the type.
    """
    try:
        return _registry[deliverable_type]
    except KeyError:
        raise KeyError(f"No provisioner registered for deliverable type: {deliverable_type!r}")


def registered_types() -> list[str]:
    return list(_registry.keys())
