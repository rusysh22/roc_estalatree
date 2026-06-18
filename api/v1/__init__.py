"""Django Ninja API — /v1/ (activation & licensing endpoints)."""
from ninja import NinjaAPI

from apps.licensing.api import router as licensing_router

api = NinjaAPI(
    title="Estalatree Activation API",
    version="1.0",
    description="Token-based license activation, validation, and deactivation.",
    urls_namespace="api_v1",
)

api.add_router("/", licensing_router)
