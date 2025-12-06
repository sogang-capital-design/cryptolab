from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db import models
from app.utils.data_utils import _get_data_path

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


class BinanceCSVLoader:
    def __init__(self, data_dir: str | None = None) -> None:
        data_root = Path(data_dir or os.getenv("BINANCE_OHLCV_DIR") or Path(_get_data_path()) / "ohlcv")
        self.data_dir = data_root

    def load_all(self, session: Session) -> int:
        if not self.data_dir.exists() or not self.data_dir.is_dir():
            logger.info("Binance OHLCV directory %s does not exist; skipping bootstrap", self.data_dir)
            return 0
        loaded = 0
        for csv_path in sorted(self.data_dir.glob("binance_ohlcv_1h_*USDT_*.csv")):
            try:
                loaded += self._load_file(session, csv_path)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to load Binance OHLCV CSV %s: %s", csv_path, exc)
        if loaded:
            session.commit()
        return loaded

    def _load_file(self, session: Session, path: Path) -> int:
        df = pd.read_csv(path, parse_dates=["datetime_utc"])
        if df.empty:
            return 0
        df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True, errors="coerce")
        df = df.dropna(subset=["datetime_utc"])
        if df.empty:
            return 0
        df["timestamp_kst"] = df["datetime_utc"].dt.tz_convert(KST).dt.tz_localize(None)
        symbol = self._extract_symbol(path.name)
        payload = [
            {
                "symbol": symbol,
                "timestamp": row["timestamp_kst"].to_pydatetime() if isinstance(row["timestamp_kst"], pd.Timestamp) else row["timestamp_kst"],
                "open_price": float(row["open"]),
                "high_price": float(row["high"]),
                "low_price": float(row["low"]),
                "close_price": float(row["close"]),
                "volume": float(row["volume"]),
                "trade_count": float(row["trade_count"]),
            }
            for _, row in df.iterrows()
        ]
        stmt = sqlite_insert(models.BinanceOHLCV).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timestamp"],
            set_={
                "open_price": stmt.excluded.open_price,
                "high_price": stmt.excluded.high_price,
                "low_price": stmt.excluded.low_price,
                "close_price": stmt.excluded.close_price,
                "volume": stmt.excluded.volume,
                "trade_count": stmt.excluded.trade_count,
            },
        )
        session.execute(stmt)
        logger.info("Loaded %s rows from %s into binance_ohlcv", len(payload), path)
        return len(payload)

    @staticmethod
    def _extract_symbol(filename: str) -> str:
        # binance_ohlcv_1h_{symbol}_{start}_{end}_utc.csv
        name = filename.replace(".csv", "")
        parts = name.split("_")
        if len(parts) < 4:
            raise ValueError(f"Unexpected Binance OHLCV filename format: {filename}")
        return parts[3]
