"""Public process liveness only; backing-service readiness is not yet checked."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Confirm that the application can serve a request without disclosing config."""
    return {"status": "ok"}
