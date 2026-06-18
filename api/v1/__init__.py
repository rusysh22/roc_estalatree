"""Django Ninja API — /v1/ (activation & licensing endpoints)."""
from ninja import NinjaAPI

api = NinjaAPI(
    title="Estalatree Activation API",
    version="1.0",
    description="Token-based license activation, validation, and deactivation.",
    urls_namespace="api_v1",
)

# Routers are added in Phase 5 when the activation endpoints are built.
# from apps.licensing.api import router as licensing_router
# api.add_router("/", licensing_router)
