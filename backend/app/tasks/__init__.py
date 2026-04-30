# PAWS Celery task modules - imported here so that autodiscover_tasks(["app.tasks"])
# in app.worker registers every @shared_task decorated function. Without these
# imports, Celery's default related_name="tasks" would look for app.tasks.tasks
# (which does not exist) and silently register nothing.
from app.tasks import cache_refresh, drift_scanner, email_tasks, resource_lifecycle  # noqa: F401
