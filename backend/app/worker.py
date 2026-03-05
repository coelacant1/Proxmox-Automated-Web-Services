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
)

celery_app.autodiscover_tasks(["app.tasks"], force=True)
