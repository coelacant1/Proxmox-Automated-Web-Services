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
        "refresh-cluster-status-cache": {
            "task": "paws.refresh_cluster_status_cache",
            "schedule": 30.0,  # every 30 seconds - keeps dashboard warm
        },
        "refresh-vm-statuses-batch": {
            "task": "paws.refresh_vm_statuses_batch",
            "schedule": 10.0,  # every 10 seconds - keeps list pages warm
        },
        "scan-drift": {
            "task": "paws.scan_drift",
            "schedule": 300.0,  # every 5 minutes
        },
    },
)

celery_app.autodiscover_tasks(["app.tasks"], force=True)
