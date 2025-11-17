import os
import time

from celery.schedules import crontab

from app.celery_app import celery_app
from app.db.database import SessionLocal
from app.services.ohlcv_service import ConfigurationError, OHLCVIngestService

service = OHLCVIngestService()
OFFSET_SECONDS = int(os.getenv("OHLCV_EXECUTION_OFFSET_SECONDS", "3"))


def _build_crontab_schedule() -> crontab:
    min_tf = service.min_base_timeframe()
    if min_tf.unit != "m":
        raise ConfigurationError("Scheduling currently supports minute-based base timeframes only.")
    minutes = min_tf.value
    if minutes <= 0:
        raise ConfigurationError("Invalid minimum timeframe.")
    if minutes < 60 and 60 % minutes == 0:
        minute_expr = f"*/{minutes}"
        return crontab(minute=minute_expr)
    if minutes == 60:
        return crontab(minute=0)
    if minutes > 60 and minutes % 60 == 0:
        hour_step = minutes // 60
        return crontab(minute=0, hour=f"*/{hour_step}")
    raise ConfigurationError(f"Unsupported minimum timeframe '{min_tf.raw}' for scheduling.")


@celery_app.task(name="ohlcv.collect_latest")
def collect_latest_ohlcv() -> None:
    if OFFSET_SECONDS > 0:
        time.sleep(OFFSET_SECONDS)
    session = SessionLocal()
    try:
        service.collect_latest(session)
    finally:
        session.close()


schedule = _build_crontab_schedule()
celery_app.conf.beat_schedule = getattr(celery_app.conf, "beat_schedule", {}) or {}
celery_app.conf.beat_schedule["collect-ohlcv-schedule"] = {
    "task": "ohlcv.collect_latest",
    "schedule": schedule,
}
celery_app.conf.timezone = "Asia/Seoul"


@celery_app.on_after_finalize.connect
def trigger_initial_collection(sender, **kwargs) -> None:
    collect_latest_ohlcv.apply_async(countdown=0)
