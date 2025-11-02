# ai/celery_app.py
import os
from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend_url = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "ai_tasks",
    broker=broker_url,
    backend=backend_url,
)
celery_app.autodiscover_tasks(["app.tasks"])