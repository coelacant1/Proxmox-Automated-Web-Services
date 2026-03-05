"""Event publisher - dispatches events and triggers hardcoded actions.

Supported action triggers:
- vm.crashed -> auto-restart (if enabled)
- backup.failed -> notify
- alarm.triggered -> notify + webhook
- quota.exceeded -> notify
"""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Admin-configurable action toggles (in-memory; production: DB/settings)
_action_config: dict[str, bool] = {
    "vm.crashed.auto_restart": True,
    "backup.failed.notify": True,
    "alarm.triggered.notify": True,
    "alarm.triggered.webhook": False,
    "quota.exceeded.notify": True,
}

# In-memory event log for recent events (ring buffer)
_event_log: list[dict[str, Any]] = []
_MAX_EVENTS = 1000


def configure_action(action_key: str, enabled: bool) -> None:
    """Enable or disable an action trigger."""
    _action_config[action_key] = enabled


def get_action_config() -> dict[str, bool]:
    """Return current action configuration."""
    return dict(_action_config)


async def publish_event(
    event_type: str,
    resource_id: str | None = None,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish an event and execute matching action triggers."""
    event = {
        "type": event_type,
        "resource_id": resource_id,
        "user_id": user_id,
        "details": details or {},
        "timestamp": datetime.now(UTC).isoformat(),
        "actions_fired": [],
    }

    # Execute matching actions
    if event_type == "vm.crashed" and _action_config.get("vm.crashed.auto_restart"):
        event["actions_fired"].append("auto_restart")
        logger.info("Auto-restart triggered for resource %s", resource_id)

    if event_type == "backup.failed" and _action_config.get("backup.failed.notify"):
        event["actions_fired"].append("notify")
        logger.info("Backup failure notification for user %s", user_id)

    if event_type == "alarm.triggered":
        if _action_config.get("alarm.triggered.notify"):
            event["actions_fired"].append("notify")
        if _action_config.get("alarm.triggered.webhook"):
            event["actions_fired"].append("webhook")
        logger.info("Alarm triggered for resource %s", resource_id)

    if event_type == "quota.exceeded" and _action_config.get("quota.exceeded.notify"):
        event["actions_fired"].append("notify")
        logger.info("Quota exceeded notification for user %s", user_id)

    # Store in ring buffer
    _event_log.append(event)
    if len(_event_log) > _MAX_EVENTS:
        _event_log.pop(0)

    return event


def get_recent_events(limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
    """Return recent events, optionally filtered by type."""
    events = _event_log
    if event_type:
        events = [e for e in events if e["type"] == event_type]
    return events[-limit:]
