import os
from typing import TYPE_CHECKING, List, Tuple

import pandas as pd
from sqlalchemy import func, select

if TYPE_CHECKING:
    from app.services.ohlcv_service import OHLCVIngestService

_ingest_service: "OHLCVIngestService | None" = None


def _get_data_path() -> str:
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "data"))
    return data_dir


def _minutes_to_timeframe_label(minutes: int) -> str:
    if minutes <= 0:
        raise ValueError("Timeframe must be positive.")
    if minutes % (60 * 24) == 0:
        days = minutes // (60 * 24)
        return f"{days}d"
    return f"{minutes}m"


def _get_ingest_service():
    global _ingest_service
    if _ingest_service is None:
        from app.services.ohlcv_service import OHLCVIngestService

        _ingest_service = OHLCVIngestService()
    return _ingest_service


def get_all_data_info() -> List[Tuple[str, pd.Timestamp, pd.Timestamp]]:
    from app.db import models
    from app.db.database import SessionLocal

    session = SessionLocal()
    try:
        query = (
            select(
                models.OHLCVRange.symbol,
                models.OHLCVRange.timeframe,
                func.min(models.OHLCVRange.start_timestamp),
                func.max(models.OHLCVRange.end_timestamp),
            )
            .group_by(models.OHLCVRange.symbol, models.OHLCVRange.timeframe)
            .order_by(models.OHLCVRange.symbol, models.OHLCVRange.timeframe)
        )
        rows = session.execute(query).all()
    finally:
        session.close()

    data_info: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
    for symbol, timeframe, start, end in rows:
        if not start or not end:
            continue
        coin_symbol = symbol.replace("KRW-", "").upper()
        data_info.append((coin_symbol, pd.Timestamp(start), pd.Timestamp(end)))
    return data_info


def get_ohlcv_df(coin_symbol: str, timeframe: int) -> pd.DataFrame:
    symbol = "KRW-" + coin_symbol.upper()
    timeframe_label = _minutes_to_timeframe_label(timeframe)

    # Validate timeframe exists in configuration
    ingest_service = _get_ingest_service()
    cfg = ingest_service.get_config(symbol)
    available = {tf.raw for tf in cfg.targets}
    if timeframe_label not in available:
        raise ValueError(f"Timeframe '{timeframe_label}' not available for {symbol}. Available: {sorted(available)}")

    from app.db.database import SessionLocal

    session = SessionLocal()
    try:
        df = ingest_service.dataframe_for_range(session, symbol, timeframe_label)
    finally:
        session.close()

    if df.empty:
        raise ValueError(f"No OHLCV data available for {coin_symbol} at {timeframe_label}.")
    return df
