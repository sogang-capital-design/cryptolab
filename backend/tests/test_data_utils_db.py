from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models
from app.db.database import Base
from app.utils import data_utils


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.database.SessionLocal", Session)
    return Session


def _naive_kst(year, month, day, hour):
    # Stored timestamps are naive KST
    return datetime(year, month, day, hour)


def test_get_total_df_joins_db_data(session_factory):
    session = session_factory()
    session.add_all(
        [
            models.BinanceOHLCV(
                symbol="1INCHUSDT",
                timestamp=_naive_kst(2024, 1, 1, 9),
                open_price=1.0,
                high_price=1.5,
                low_price=0.5,
                close_price=1.2,
                volume=100.0,
                trade_count=10,
            ),
            models.BinanceOHLCV(
                symbol="1INCHUSDT",
                timestamp=_naive_kst(2024, 1, 1, 10),
                open_price=1.2,
                high_price=1.6,
                low_price=1.0,
                close_price=1.3,
                volume=150.0,
                trade_count=12,
            ),
        ]
    )
    for hour_offset, symbol in ((9, "KRW-1INCH"), (10, "KRW-1INCH"), (9, "KRW-USDT"), (10, "KRW-USDT")):
        session.add(
            models.Onchain(
                hour=_naive_kst(2024, 1, 1, hour_offset),
                symbol=symbol,
                total_volume=1.0,
                total_tx_count=2.0,
                cex_inflow=3.0,
                cex_outflow=4.0,
                cex_tx_count=5.0,
                dex_inflow=6.0,
                dex_outflow=7.0,
                dex_tx_count=8.0,
                inst_inflow=9.0,
                inst_outflow=10.0,
                inst_tx_count=11.0,
            )
        )
    session.commit()
    session.close()

    df = data_utils.get_total_df("1INCH")
    assert not df.empty
    assert list(df.index) == [pd.Timestamp("2024-01-01 00:00:00+0000", tz="UTC"), pd.Timestamp("2024-01-01 01:00:00+0000", tz="UTC")]
    assert "usdt_total_volume" in df.columns
    assert df["open"].iloc[0] == 1.0


def test_get_all_data_info_reads_ranges(session_factory):
    session = session_factory()
    session.add_all(
        [
            models.OnchainRange(
                symbol="KRW-PEPE",
                timeframe="60m",
                start_timestamp=_naive_kst(2024, 1, 1, 9),
                end_timestamp=_naive_kst(2024, 1, 1, 11),
            ),
            models.OnchainRange(
                symbol="KRW-LINK",
                timeframe="60m",
                start_timestamp=_naive_kst(2024, 1, 2, 9),
                end_timestamp=_naive_kst(2024, 1, 2, 10),
            ),
        ]
    )
    session.commit()
    session.close()

    info = data_utils.get_all_data_info()
    assert info[0][0] == "LINK"
    start_ts = info[0][1]
    assert start_ts.tzinfo == pd.Timestamp("2024-01-01", tz="UTC").tzinfo
    assert start_ts == pd.Timestamp("2024-01-02 00:00:00", tz="UTC")
