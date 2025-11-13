from datetime import datetime, timedelta

import pytest

from app.services.ohlcv_service import (
    KST,
    OHLCVIngestService,
    OHLCVRangeCalculator,
    parse_timeframe,
)


def test_ohlcv_range_calculator_subtract_handles_overlap():
    existing = [
        (
            datetime(2025, 1, 1, 0, 0, tzinfo=KST),
            datetime(2025, 1, 1, 1, 0, tzinfo=KST),
        ),
        (
            datetime(2025, 1, 1, 1, 30, tzinfo=KST),
            datetime(2025, 1, 1, 2, 0, tzinfo=KST),
        ),
    ]
    target = (
        datetime(2025, 1, 1, 0, 30, tzinfo=KST),
        datetime(2025, 1, 1, 2, 30, tzinfo=KST),
    )

    missing = OHLCVRangeCalculator.subtract(existing, target)

    assert missing == [
        (
            datetime(2025, 1, 1, 1, 0, tzinfo=KST),
            datetime(2025, 1, 1, 1, 30, tzinfo=KST),
        ),
        (
            datetime(2025, 1, 1, 2, 0, tzinfo=KST),
            datetime(2025, 1, 1, 2, 30, tzinfo=KST),
        ),
    ]


def test_harvest_range_interpolates_and_drops_trailing(monkeypatch):
    service = OHLCVIngestService()
    timeframe = parse_timeframe("1m")
    delta = timeframe.to_timedelta()
    start = datetime(2025, 1, 1, 0, 0, tzinfo=KST)
    end = start + timedelta(minutes=4)
    request_time = start + timedelta(minutes=3, seconds=30)

    def make_candle(ts, price):
        return {
            "symbol": "KRW-BTC",
            "timeframe": timeframe.raw,
            "timestamp": ts,
            "opening_price": price,
            "high_price": price,
            "low_price": price,
            "trade_price": price,
            "candle_acc_trade_price": price * 10,
            "candle_acc_trade_volume": 1.0,
        }

    actual_candles = {
        start: make_candle(start, 100.0),
        start + timedelta(minutes=3): make_candle(start + timedelta(minutes=3), 130.0),
    }

    def fake_download(self, symbol, tf, seg_start, seg_end):
        records = []
        current = seg_start
        while current < seg_end:
            candle = actual_candles.get(current)
            if candle:
                records.append(candle)
            current += delta
        return records

    monkeypatch.setattr(OHLCVIngestService, "_download_segment", fake_download, raising=False)

    harvested = service._harvest_range(None, "KRW-BTC", timeframe, start, end, request_time=request_time)

    timestamps = [row["timestamp"] for row in harvested]
    assert timestamps == [
        start,
        start + delta,
        start + 2 * delta,
    ], "trailing candle should be dropped when too close to request time"

    interpolated = harvested[1]
    assert interpolated["opening_price"] == actual_candles[start]["trade_price"]
    assert interpolated["trade_price"] == actual_candles[start]["trade_price"]
