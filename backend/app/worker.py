from celery import Celery

from app.core.config import settings

celery_app = Celery("paws", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # RedBeat scheduler config
    redbeat_redis_url=settings.redis_url,
    redbeat_lock_timeout=30,
    # Periodic tasks
    beat_schedule={
        "enforce-resource-lifecycle": {
            "task": "paws.enforce_resource_lifecycle",
            "schedule": 3600.0,  # every hour
        },
        "enforce-account-lifecycle": {
            "task": "paws.enforce_account_lifecycle",
            "schedule": 86400.0,  # daily
        },
        "enforce-quota": {
            "task": "paws.enforce_quota",
            "schedule": 900.0,  # every 15 minutes
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"], force=True)
