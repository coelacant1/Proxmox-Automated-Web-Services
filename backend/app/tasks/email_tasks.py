"""Celery tasks for sending email notifications."""

import logging
from typing import Any

from celery import shared_task

log = logging.getLogger(__name__)


def _run_async(coro):  # noqa: ANN001
    from app.tasks._async_runner import run_task_async

    return run_task_async(coro)


async def _send_notification(user_id: str, template_name: str, context: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.models import User
    from app.services.email_service import send_template_email

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            log.warning("Email task: user %s not found", user_id)
            return
        if not user.email_notifications:
            log.debug("Email task: user %s has notifications disabled", user_id)
            return
        if not user.email:
            log.debug("Email task: user %s has no email address", user_id)
            return

        # Enrich context with user info
        ctx = {**context, "username": user.username, "email": user.email}
        await send_template_email(db, user.email, template_name, ctx)


@shared_task(name="paws.send_notification_email", ignore_result=True, max_retries=3)
def send_notification_email(user_id: str, template_name: str, context: dict[str, Any]) -> None:
    """Send a notification email to a user (runs in Celery worker)."""
    _run_async(_send_notification(user_id, template_name, context))
