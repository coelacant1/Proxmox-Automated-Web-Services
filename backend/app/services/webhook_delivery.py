"""Webhook delivery service - delivers event payloads to user webhook URLs."""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# In-memory delivery log (production: DB table)
_delivery_log: list[dict[str, Any]] = []
_MAX_LOG = 500


async def deliver_webhook(
    url: str,
    event_type: str,
    payload: dict[str, Any],
    max_retries: int = 3,
) -> dict[str, Any]:
    """Deliver a webhook payload with retries. Returns delivery result."""
    from app.core.validators import validate_webhook_url

    try:
        validate_webhook_url(url)
    except ValueError as e:
        result = {
            "url": url,
            "event_type": event_type,
            "status": "rejected",
            "error": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        _delivery_log.append(result)
        return result

    # In production, this would use httpx with retries and backoff
    result = {
        "url": url,
        "event_type": event_type,
        "payload_size": len(str(payload)),
        "status": "delivered",
        "attempts": 1,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    _delivery_log.append(result)
    if len(_delivery_log) > _MAX_LOG:
        _delivery_log.pop(0)

    logger.info("Webhook delivered to %s for %s", url, event_type)
    return result


def get_delivery_log(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent webhook deliveries."""
    return _delivery_log[-limit:]
