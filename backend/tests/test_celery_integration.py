from types import SimpleNamespace

import pytest

from app.celery_app import celery_app
from app.tasks import ohlcv_ingest_task
from app.tasks.ohlcv_ingest_task import collect_latest_ohlcv


@pytest.fixture(autouse=True)
def eager_celery():
    previous_always_eager = celery_app.conf.task_always_eager
    previous_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        yield
    finally:
        celery_app.conf.task_always_eager = previous_always_eager
        celery_app.conf.task_eager_propagates = previous_propagates


def test_collect_latest_task_invokes_service(monkeypatch):
    class DummySession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    dummy_session = DummySession()
    monkeypatch.setattr(ohlcv_ingest_task, "SessionLocal", lambda: dummy_session)

    class DummyService:
        def __init__(self):
            self.call_count = 0

        def collect_latest(self, session):
            self.call_count += 1
            assert session is dummy_session

    dummy_service = DummyService()
    monkeypatch.setattr(ohlcv_ingest_task, "service", dummy_service)

    async_result = collect_latest_ohlcv.delay()
    assert async_result.successful()
    assert dummy_service.call_count == 1
    assert dummy_session.closed
