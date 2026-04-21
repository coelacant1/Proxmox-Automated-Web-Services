import time

from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.models.models import User

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "paws-api"}


@router.get("/health/detailed")
async def health_detailed(_: User = Depends(require_admin)):
    """Admin-only detailed health: per-subsystem status with latency."""
    subsystems = {}

    # Database check
    t0 = time.monotonic()
    try:
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        subsystems["database"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as e:
        subsystems["database"] = {"status": "error", "error": str(e)}

    # Proxmox API check
    t0 = time.monotonic()
    try:
        from app.services.proxmox_client import get_pve

        get_pve().get_nodes()
        subsystems["proxmox"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as e:
        subsystems["proxmox"] = {"status": "error", "error": str(e)}

    overall = "healthy" if all(s["status"] == "ok" for s in subsystems.values()) else "degraded"
    return {"status": overall, "subsystems": subsystems}
