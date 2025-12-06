from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db import models
from app.services.binance_csv_loader import BinanceCSVLoader


@pytest.fixture
def session(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def _write_binance_csv(path: Path, rows: list[dict[str, str | float]]) -> None:
    headers = ["datetime_utc", "open", "high", "low", "close", "volume", "trade_count"]
    lines = [",".join(headers)]
    for row in rows:
        lines.append(
            ",".join(str(row[col]) for col in headers)
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def test_loader_inserts_rows_and_converts_to_kst(tmp_path, session):
    csv_dir = tmp_path / "ohlcv"
    csv_dir.mkdir()
    csv_path = csv_dir / "binance_ohlcv_1h_1INCHUSDT_20240101_20240102_utc.csv"
    rows = [
        {
            "datetime_utc": "2024-01-01 00:00:00+00:00",
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 100.0,
            "trade_count": 10,
        },
        {
            "datetime_utc": "2024-01-01 01:00:00+00:00",
            "open": 2.0,
            "high": 3.0,
            "low": 1.5,
            "close": 2.5,
            "volume": 200.0,
            "trade_count": 20,
        },
    ]
    _write_binance_csv(csv_path, rows)

    loader = BinanceCSVLoader(data_dir=str(csv_dir))
    inserted = loader.load_all(session)
    assert inserted == 2

    stored = session.execute(select(models.BinanceOHLCV)).scalars().all()
    assert len(stored) == 2
    first = stored[0]
    assert first.symbol == "1INCHUSDT"
    expected_ts = datetime(2024, 1, 1, 9, 0)
    assert first.timestamp == expected_ts
    assert first.volume == 100.0


def test_loader_is_idempotent(tmp_path, session):
    csv_dir = tmp_path / "ohlcv"
    csv_dir.mkdir()
    csv_path = csv_dir / "binance_ohlcv_1h_LINKUSDT_20240101_20240102_utc.csv"
    rows = [
        {
            "datetime_utc": "2024-01-01 00:00:00+00:00",
            "open": 4.0,
            "high": 5.0,
            "low": 3.0,
            "close": 4.5,
            "volume": 50.0,
            "trade_count": 5,
        },
    ]
    _write_binance_csv(csv_path, rows)

    loader = BinanceCSVLoader(data_dir=str(csv_dir))
    loader.load_all(session)
    loader.load_all(session)

    stored = session.execute(select(models.BinanceOHLCV)).scalars().all()
    assert len(stored) == 1
    assert stored[0].symbol == "LINKUSDT"
