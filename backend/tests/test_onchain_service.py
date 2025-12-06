from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import models
from app.db.database import Base
from app.services.onchain_service import OnchainIngestService
from app.services.ohlcv_service import ensure_kst, normalize_timestamp


@pytest.fixture
def in_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def base_env(monkeypatch):
    monkeypatch.setenv("DUNE_API_KEY", "test-key")
    monkeypatch.setenv("OHLCV_COLLECT_START", "2024-01-01T00:00:00")


def _write_onchain_csv(path, rows):
    headers = [
        "hour",
        "total_volume",
        "total_tx_count",
        "cex_inflow",
        "cex_outflow",
        "cex_tx_count",
        "dex_inflow",
        "dex_outflow",
        "dex_tx_count",
        "inst_inflow",
        "inst_outflow",
        "inst_tx_count",
    ]
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(row[col]) for col in headers))
    path.write_text("\n".join(lines), encoding="utf-8")


def test_bootstrap_ingests_csv_and_records_range(tmp_path, monkeypatch, in_memory_session):
    monkeypatch.setenv("ONCHAIN_DATA_DIR", str(tmp_path))
    csv_path = tmp_path / "PEPE_60m_20240101_20240102.csv"
    rows = [
        {
            "hour": "2024-01-01 00:00:00",
            "total_volume": 1,
            "total_tx_count": 2,
            "cex_inflow": 3,
            "cex_outflow": 4,
            "cex_tx_count": 5,
            "dex_inflow": 6,
            "dex_outflow": 7,
            "dex_tx_count": 8,
            "inst_inflow": 9,
            "inst_outflow": 10,
            "inst_tx_count": 11,
        },
        {
            "hour": "2024-01-01 01:00:00",
            "total_volume": 12,
            "total_tx_count": 13,
            "cex_inflow": 14,
            "cex_outflow": 15,
            "cex_tx_count": 16,
            "dex_inflow": 17,
            "dex_outflow": 18,
            "dex_tx_count": 19,
            "inst_inflow": 20,
            "inst_outflow": 21,
            "inst_tx_count": 22,
        },
    ]
    _write_onchain_csv(csv_path, rows)

    service = OnchainIngestService()
    service._bootstrap_from_csv(in_memory_session)

    stored_rows = in_memory_session.execute(select(models.Onchain)).scalars().all()
    stored_rows.sort(key=lambda row: row.hour)
    assert len(stored_rows) == 2

    expected_first_hour = ensure_kst(datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)).replace(tzinfo=None)
    assert stored_rows[0].hour == expected_first_hour

    ranges = in_memory_session.execute(select(models.OnchainRange)).scalars().all()
    assert len(ranges) == 1
    assert ranges[0].symbol == "KRW-PEPE"


def test_collect_latest_fetches_from_dune_based_on_ohlcv_range(tmp_path, monkeypatch, in_memory_session):
    monkeypatch.setenv("ONCHAIN_DATA_DIR", str(tmp_path))
    service = OnchainIngestService()
    monkeypatch.setattr(service, "_current_request_time", lambda: ensure_kst(datetime(2024, 1, 1, 15, 0)))

    class DummyDuneClient:
        def __init__(self):
            self.calls: list[tuple[int, dict[str, str]]] = []

        def fetch(self, query_id: int, params: dict[str, str]):
            self.calls.append((query_id, params))
            rows = []
            start_utc = datetime(2023, 12, 31, 15, 0, tzinfo=timezone.utc)
            for i in range(4):
                cursor = start_utc + timedelta(hours=i)
                rows.append(
                    {
                        "hour": cursor.strftime("%Y-%m-%d %H:%M:%S"),
                        "total_volume": 1,
                        "total_tx_count": 1,
                        "cex_inflow": 1,
                        "cex_outflow": 1,
                        "cex_tx_count": 1,
                        "dex_inflow": 1,
                        "dex_outflow": 1,
                        "dex_tx_count": 1,
                        "inst_inflow": 1,
                        "inst_outflow": 1,
                        "inst_tx_count": 1,
                    }
                )
            return rows

    dummy_client = DummyDuneClient()
    service.dune_client = dummy_client

    start = ensure_kst(datetime(2024, 1, 1, 0, 0))
    end = start + timedelta(hours=5)
    in_memory_session.add(
        models.OHLCVRange(
            timeframe="60m",
            symbol="KRW-PEPE",
            start_timestamp=normalize_timestamp(start),
            end_timestamp=normalize_timestamp(end),
        )
    )
    in_memory_session.commit()

    service.collect_latest(in_memory_session)

    assert dummy_client.calls, "Dune client should be invoked for missing onchain data"
    assert any(call[0] == 6295814 for call in dummy_client.calls)
    for query_id, params in dummy_client.calls:
        if query_id == 6295814:
            assert params["token_address"].startswith("0x")
            assert params["start_ts"] == "2023-12-31 15:00:00"
            break

    stored_rows = in_memory_session.execute(select(models.Onchain)).scalars().all()
    pepe_rows = [row for row in stored_rows if row.symbol == "KRW-PEPE"]
    assert len(pepe_rows) == 4

    ranges = in_memory_session.execute(select(models.OnchainRange)).scalars().all()
    pepe_range = next(r for r in ranges if r.symbol == "KRW-PEPE")
    expected_end = normalize_timestamp(ensure_kst(datetime(2024, 1, 1, 4, 0)))
    assert pepe_range.end_timestamp == expected_end


def test_collect_latest_without_ohlcv_range_uses_request_time(tmp_path, monkeypatch, in_memory_session):
    monkeypatch.setenv("ONCHAIN_DATA_DIR", str(tmp_path))
    service = OnchainIngestService()
    monkeypatch.setattr(service, "_current_request_time", lambda: ensure_kst(datetime(2024, 1, 1, 15, 0)))

    captured = {}

    def fake_harvest(self, cfg, start, end, request_time=None):
        captured["range"] = (start, end)
        rows = []
        cursor = start
        delta = cfg.base.to_timedelta()
        while cursor < end:
            rows.append(
                {
                    "hour": cursor,
                    "symbol": cfg.symbol,
                    "total_volume": 1.0,
                    "total_tx_count": 1.0,
                    "cex_inflow": 1.0,
                    "cex_outflow": 1.0,
                    "cex_tx_count": 1.0,
                    "dex_inflow": 1.0,
                    "dex_outflow": 1.0,
                    "dex_tx_count": 1.0,
                    "inst_inflow": 1.0,
                    "inst_outflow": 1.0,
                    "inst_tx_count": 1.0,
                }
            )
            cursor += delta
        return rows

    monkeypatch.setattr(OnchainIngestService, "_harvest_range", fake_harvest, raising=False)
    service.collect_latest(in_memory_session)
    assert "range" in captured
    _, end = captured["range"]
    assert end == ensure_kst(datetime(2024, 1, 1, 14, 0))
