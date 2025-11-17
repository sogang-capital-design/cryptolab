from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Iterator, List, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml
from sqlalchemy import and_, select, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db import models

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
UPBIT_MAX_COUNT = 200


class ConfigurationError(RuntimeError):
    """Raised when OHLCV ingest settings are invalid."""


@dataclass(frozen=True)
class TimeframeSpec:
    raw: str
    value: int
    unit: str  # m, d, w, M, y

    @property
    def pandas_freq(self) -> str:
        suffix_map = {"m": "min", "d": "D", "w": "W", "M": "M", "y": "Y"}
        return f"{self.value}{suffix_map[self.unit]}"

    @property
    def label(self) -> str:
        unit_names = {"m": "minutes", "d": "days", "w": "weeks", "M": "months", "y": "years"}
        return f"{self.value} {unit_names[self.unit]}"

    def to_timedelta(self) -> timedelta:
        if self.unit == "m":
            return timedelta(minutes=self.value)
        if self.unit == "d":
            return timedelta(days=self.value)
        if self.unit == "w":
            return timedelta(weeks=self.value)
        raise ConfigurationError(f"Timeframe '{self.raw}' cannot be represented as timedelta.")


def parse_timeframe(raw: str) -> TimeframeSpec:
    raw = raw.strip()
    if not raw:
        raise ConfigurationError("Empty timeframe string.")
    suffix = raw[-1]
    if suffix not in {"m", "d", "w", "M", "y"}:
        raise ConfigurationError(f"Unsupported timeframe unit '{suffix}' in '{raw}'.")
    value_part = raw[:-1]
    if not value_part.isdigit():
        raise ConfigurationError(f"Invalid timeframe value '{raw}'.")
    value = int(value_part)
    if value <= 0:
        raise ConfigurationError(f"Timeframe value must be positive in '{raw}'.")
    return TimeframeSpec(raw=raw, value=value, unit=suffix)


def ensure_kst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def normalize_timestamp(dt: datetime) -> datetime:
    return ensure_kst(dt).replace(tzinfo=None)


def timeframe_minutes(tf: TimeframeSpec) -> int | None:
    unit_factor = {"m": 1, "d": 60 * 24, "w": 60 * 24 * 7}
    if tf.unit not in unit_factor:
        return None
    return tf.value * unit_factor[tf.unit]


def can_aggregate(source: TimeframeSpec, target: TimeframeSpec) -> bool:
    if source.raw == target.raw:
        return False
    if target.unit in {"m", "d", "w"}:
        target_minutes = timeframe_minutes(target)
        source_minutes = timeframe_minutes(source)
        if target_minutes is None or source_minutes is None:
            return False
        if target_minutes <= source_minutes:
            return False
        return target_minutes % source_minutes == 0
    if target.unit in {"M", "y"}:
        return source.unit == "d" and source.value == 1
    return False


@dataclass
class SymbolTimeframeConfig:
    symbol: str
    base: TimeframeSpec
    targets: list[TimeframeSpec]

    def __post_init__(self) -> None:
        unique_targets = {tf.raw: tf for tf in self.targets}
        if self.base.raw not in unique_targets:
            unique_targets[self.base.raw] = self.base
        self.targets = sorted(unique_targets.values(), key=lambda tf: timeframe_sort_key(tf))
        self._timeframe_map = {tf.raw: tf for tf in self.targets}
        self._validate_base_supported()
        self.validate_hierarchy()

    def _validate_base_supported(self) -> None:
        if self.base.unit == "m":
            allowed_minutes = {1, 3, 5, 15, 30, 60, 240}
            if self.base.value not in allowed_minutes:
                raise ConfigurationError(
                    f"Upbit minutes candles support only {sorted(allowed_minutes)}; got {self.base.raw}"
                )
        elif self.base.unit in {"d", "w", "M", "y"}:
            if self.base.value != 1:
                raise ConfigurationError(
                    f"Upbit {self.base.unit} candles support only unit value 1; got {self.base.raw}"
                )
        else:
            raise ConfigurationError(f"Unsupported base timeframe '{self.base.raw}' for Upbit.")

    def validate_hierarchy(self) -> None:
        available = {self.base.raw}
        for tf in self.targets:
            if tf.raw == self.base.raw:
                continue
            source = self._select_source_timeframe(tf, available)
            if source is None:
                raise ConfigurationError(
                    f"No aggregation path found for {tf.raw}. Ensure smaller divisible timeframe exists."
                )
            available.add(tf.raw)

    @property
    def max_timeframe(self) -> TimeframeSpec:
        return self.targets[-1]

    def get_timeframe(self, raw: str) -> TimeframeSpec:
        return self._timeframe_map[raw]

    def _select_source_timeframe(
        self, target: TimeframeSpec, available_raws: Iterable[str]
    ) -> TimeframeSpec | None:
        candidates: list[TimeframeSpec] = []
        for raw in available_raws:
            source = self._timeframe_map.get(raw)
            if not source:
                continue
            if timeframe_sort_key(source) >= timeframe_sort_key(target):
                continue
            if can_aggregate(source, target):
                candidates.append(source)
        if not candidates:
            return None
        return max(candidates, key=timeframe_sort_key)

    def select_source_for_target(
        self, target: TimeframeSpec, available_raws: Iterable[str]
    ) -> TimeframeSpec:
        source = self._select_source_timeframe(target, available_raws)
        if source is None:
            raise ConfigurationError(f"Cannot find aggregation source for {target.raw}")
        return source


def timeframe_sort_key(tf: TimeframeSpec) -> int:
    unit_factor = {"m": 1, "d": 60 * 24, "w": 60 * 24 * 7, "M": 60 * 24 * 30, "y": 60 * 24 * 365}
    return tf.value * unit_factor[tf.unit]


def load_symbol_configs(config_path: str, default_targets: Sequence[str]) -> list[SymbolTimeframeConfig]:
    if not os.path.exists(config_path):
        raise ConfigurationError(f"Config file '{config_path}' not found.")
    with open(config_path, "r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    pairs = data.get("pairs", [])
    configs: list[SymbolTimeframeConfig] = []
    for item in pairs:
        symbol = item["symbol"]
        base_raw = item["base_timeframe"]
        targets_raw = item.get("target_timeframes") or list(default_targets)
        base = parse_timeframe(base_raw)
        targets = [parse_timeframe(raw) for raw in targets_raw]
        configs.append(SymbolTimeframeConfig(symbol=symbol, base=base, targets=targets))
    return configs


class UpbitClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._next_delay = 0.0
        self._max_http_retry = 3

    def fetch_candles(
        self,
        timeframe: TimeframeSpec,
        market: str,
        to: datetime | None,
        count: int,
    ) -> list[dict]:
        endpoint = self._build_endpoint(timeframe)
        params = {"market": market, "count": count}
        if to is not None:
            params["to"] = to.astimezone(KST).isoformat()

        last_exc: Exception | None = None
        for _ in range(self._max_http_retry):
            self._respect_rate_limit()
            response = self.session.get(f"{self.base_url}{endpoint}", params=params, timeout=10)
            if response.status_code == 429:
                self._update_rate_limit_from_headers(response.headers, fallback=1.0)
                continue
            try:
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                break
            self._update_rate_limit_from_headers(response.headers)
            return response.json()
        if last_exc:
            raise last_exc
        response.raise_for_status()

    def _respect_rate_limit(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._next_delay:
                time.sleep(self._next_delay - elapsed)
            self._last_call = time.monotonic()
            self._next_delay = 0.0

    def _update_rate_limit_from_headers(self, headers: dict[str, str], fallback: float = 0.0) -> None:
        remaining = headers.get("Remaining-Req") or ""
        rate_hint: dict[str, str] = {}
        for token in remaining.split(";"):
            if "=" in token:
                k, v = token.strip().split("=", 1)
                rate_hint[k] = v
        try:
            sec_left = int(rate_hint.get("sec", "0"))
        except ValueError:
            sec_left = 0
        delay = fallback
        if sec_left <= 1:
            delay = max(delay, 1.0)
        elif sec_left <= 5:
            delay = max(delay, 0.5)
        elif sec_left <= 10:
            delay = max(delay, 0.2)
        with self._lock:
            self._next_delay = max(self._next_delay, delay)

    @staticmethod
    def _build_endpoint(timeframe: TimeframeSpec) -> str:
        if timeframe.unit == "m":
            return f"/candles/minutes/{timeframe.value}"
        if timeframe.unit == "d":
            return "/candles/days"
        if timeframe.unit == "w":
            return "/candles/weeks"
        if timeframe.unit == "M":
            return "/candles/months"
        if timeframe.unit == "y":
            return "/candles/years"
        raise ConfigurationError(f"Unsupported timeframe '{timeframe.raw}' for Upbit.")


class OHLCVRangeCalculator:
    @staticmethod
    def subtract(existing: Sequence[tuple[datetime, datetime]], target: tuple[datetime, datetime]) -> list[tuple[datetime, datetime]]:
        start, end = target
        missing: list[tuple[datetime, datetime]] = []
        cursor = start
        for cur_start, cur_end in sorted(existing):
            if cur_end <= cursor:
                continue
            if cur_start > end:
                break
            if cur_start > cursor:
                missing.append((cursor, min(cur_start, end)))
            cursor = max(cursor, cur_end)
            if cursor >= end:
                break
        if cursor < end:
            missing.append((cursor, end))
        return [(s, e) for s, e in missing if s < e]


class OHLCVIngestService:
    def __init__(self) -> None:
        self.config_path = os.getenv("OHLCV_CONFIG_PATH", "config/ohlcv_settings.yml")
        default_targets_env = os.getenv("DEFAULT_TARGET_TIMEFRAMES", "60m,240m,1d")
        default_targets = [item.strip() for item in default_targets_env.split(",") if item.strip()]
        self.symbol_configs = load_symbol_configs(self.config_path, default_targets)

        self.collect_start = self._parse_collect_start(os.getenv("OHLCV_COLLECT_START"))
        self.max_retry = int(os.getenv("OHLCV_RETRY_LIMIT", "1"))  # 재시도 1회
        self.api_client = UpbitClient(
            base_url=os.getenv("UPBIT_API_BASE_URL", "https://api.upbit.com/v1"),
        )
        self.collection_delay_seconds = int(os.getenv("OHLCV_COLLECTION_INTERVAL_SECONDS", "300"))

    @staticmethod
    def _parse_collect_start(raw: str | None) -> datetime:
        if not raw:
            raise ConfigurationError("OHLCV_COLLECT_START must be set (e.g., '2024-01-01T00:00:00').")
        try:
            dt = datetime.fromisoformat(raw)
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError(f"Invalid OHLCV_COLLECT_START: '{raw}'") from exc
        return ensure_kst(dt)

    def get_config(self, symbol: str) -> SymbolTimeframeConfig:
        for cfg in self.symbol_configs:
            if cfg.symbol == symbol:
                return cfg
        raise ConfigurationError(f"Symbol '{symbol}' not found in OHLCV config.")

    def min_base_timeframe(self) -> TimeframeSpec:
        return min((cfg.base for cfg in self.symbol_configs), key=timeframe_sort_key)

    def collect_latest(self, session: Session) -> None:
        request_time = datetime.now(tz=KST)
        for cfg in self.symbol_configs:
            base = cfg.base
            end = align_timestamp(request_time, base)
            start = align_timestamp(self.collect_start, base)
            if start >= end:
                continue
            logger.debug(
                "Collecting %s from %s to %s (%s)",
                cfg.symbol,
                start,
                end,
                base.raw,
            )
            self.collect_range(session, cfg.symbol, base.raw, start, end, request_time=request_time)
            session.commit()

    def collect_range(self, session: Session, symbol: str, timeframe_raw: str, start: datetime, end: datetime, request_time: datetime | None = None) -> None:
        cfg = self.get_config(symbol)
        base_tf = cfg.base
        if timeframe_raw != base_tf.raw:
            raise ConfigurationError("수집 요청은 항상 base timeframe 기준으로 진행해야 합니다.")
        existing_ranges = self._fetch_ranges(session, symbol, base_tf.raw)
        missing_ranges = OHLCVRangeCalculator.subtract(existing_ranges, (start, end))
        for missing_start, missing_end in missing_ranges:
            capture_request_time = request_time if (request_time and missing_end == end) else None
            harvested = self._harvest_range(session, symbol, base_tf, missing_start, missing_end, request_time=capture_request_time)
            if not harvested:
                continue
            self._persist_candles(session, symbol, base_tf, harvested)
            range_start = harvested[0]["timestamp"]
            range_end = harvested[-1]["timestamp"] + base_tf.to_timedelta()
            if self._is_range_complete(session, symbol, base_tf, range_start, range_end):
                if not self._range_covered(session, symbol, base_tf.raw, range_start, range_end):
                    self._record_range(session, symbol, base_tf.raw, range_start, range_end)
                    self._merge_ranges(session, symbol, base_tf.raw)
            else:
                logger.warning(
                    "Skipping range record for %s %s [%s, %s): missing candles",
                    symbol,
                    base_tf.raw,
                    range_start,
                    range_end,
                )
            self._build_aggregations(session, symbol, cfg, range_start, harvested[-1]["timestamp"])

    def dataframe_for_range(
        self,
        session: Session,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        query = select(models.OHLCV).where(
            and_(models.OHLCV.symbol == symbol, models.OHLCV.timeframe == timeframe)
        )
        if start is not None:
            query = query.where(models.OHLCV.timestamp >= start)
        if end is not None:
            query = query.where(models.OHLCV.timestamp <= end)
        query = query.order_by(models.OHLCV.timestamp.asc())
        rows = session.execute(query).scalars().all()
        records = [
            {
                "datetime": row.timestamp,
                "open": row.opening_price,
                "high": row.high_price,
                "low": row.low_price,
                "close": row.trade_price,
                "volume": row.candle_acc_trade_volume,
                "value": row.candle_acc_trade_price,
            }
            for row in rows
        ]
        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "value"])
        df = df.set_index("datetime").sort_index()
        return df

    def _harvest_range(
        self,
        session: Session,
        symbol: str,
        timeframe: TimeframeSpec,
        start: datetime,
        end: datetime,
        request_time: datetime | None = None,
    ) -> list[dict]:
        expected = list(generate_expected_timestamps(start, end, timeframe))
        if not expected:
            return []
        harvested: dict[datetime, dict] = {}
        pending_segments = [(start, end)]
        attempt = 0
        while pending_segments and attempt <= self.max_retry:
            next_segments: list[tuple[datetime, datetime]] = []
            for seg_start, seg_end in pending_segments:
                logger.debug(
                    "Downloading segment %s %s [%s, %s) attempt=%s",
                    symbol,
                    timeframe.raw,
                    seg_start,
                    seg_end,
                    attempt,
                )
                downloaded = self._download_segment(symbol, timeframe, seg_start, seg_end)
                for candle in downloaded:
                    harvested[candle["timestamp"]] = candle
                missing = find_missing_timestamps(seg_start, seg_end, timeframe, harvested)
                next_segments.extend(missing)
            pending_segments = next_segments
            attempt += 1
        if pending_segments:
            for seg_start, seg_end in pending_segments:
                interpolated = interpolate_candles(seg_start, seg_end, timeframe, harvested)
                for candle in interpolated:
                    harvested[candle["timestamp"]] = candle
            logger.debug(
                "Interpolated %s candles for %s %s gaps=%s",
                len(harvested),
                symbol,
                timeframe.raw,
                pending_segments,
            )
        sorted_records = [harvested[ts] for ts in sorted(harvested.keys()) if start <= ts < end]
        if request_time is not None and sorted_records:
            last_ts = sorted_records[-1]["timestamp"]
            if request_time - last_ts < timeframe.to_timedelta():
                logger.debug(
                    "Dropping trailing candle for %s %s at %s (pending confirmation)",
                    symbol,
                    timeframe.raw,
                    last_ts,
                )
                sorted_records.pop()
        return sorted_records

    def _download_segment(
        self,
        symbol: str,
        timeframe: TimeframeSpec,
        seg_start: datetime,
        seg_end: datetime,
    ) -> list[dict]:
        delta = timeframe.to_timedelta()
        candles: list[dict] = []
        cursor = seg_end
        remaining = math.ceil((seg_end - seg_start) / delta)
        while remaining > 0:
            batch = min(UPBIT_MAX_COUNT, remaining)
            payload = self.api_client.fetch_candles(timeframe, symbol, cursor, batch)
            if not payload:
                break
            for item in payload:
                ts = datetime.fromisoformat(item["candle_date_time_kst"]).replace(tzinfo=KST)
                candle_start = ts - delta
                record = {
                    "symbol": symbol,
                    "timeframe": timeframe.raw,
                    "timestamp": candle_start,
                    "opening_price": float(item["opening_price"]),
                    "high_price": float(item["high_price"]),
                    "low_price": float(item["low_price"]),
                    "trade_price": float(item["trade_price"]),
                    "candle_acc_trade_price": float(item["candle_acc_trade_price"]),
                    "candle_acc_trade_volume": float(item["candle_acc_trade_volume"]),
                }
                candles.append(record)
            remaining -= len(payload)
            cursor = candles[-1]["timestamp"] if candles else cursor - delta
            if cursor <= seg_start:
                break
        logger.debug(
            "Downloaded %s candles from Upbit for %s %s",
            len(candles),
            symbol,
            timeframe.raw,
        )
        return candles

    def _persist_candles(
        self,
        session: Session,
        symbol: str,
        timeframe: TimeframeSpec,
        records: list[dict],
    ) -> None:
        if not records:
            return
        payload: list[dict] = []
        for record in records:
            payload.append(
                {
                    "timeframe": timeframe.raw,
                    "symbol": symbol,
                    "timestamp": normalize_timestamp(record["timestamp"]),
                    "opening_price": record["opening_price"],
                    "high_price": record["high_price"],
                    "low_price": record["low_price"],
                    "trade_price": record["trade_price"],
                    "candle_acc_trade_price": record["candle_acc_trade_price"],
                    "candle_acc_trade_volume": record["candle_acc_trade_volume"],
                }
            )
        self._upsert_candles(session, payload)
        logger.debug(
            "Persisted %s raw candles for %s %s [%s, %s]",
            len(records),
            symbol,
            timeframe.raw,
            records[0]["timestamp"],
            records[-1]["timestamp"],
        )

    def _build_aggregations(
        self,
        session: Session,
        symbol: str,
        cfg: SymbolTimeframeConfig,
        start: datetime,
        end: datetime,
    ) -> None:
        start = normalize_timestamp(start)
        end = normalize_timestamp(end)
        base_tf = cfg.base
        base_df = self.dataframe_for_range(session, symbol, base_tf.raw, start, end)
        if base_df.empty:
            return
        if getattr(base_df.index, "tz", None) is None:
            base_df = base_df.tz_localize(KST, nonexistent="shift_forward", ambiguous="NaT")
        start_ts = pd.Timestamp(start, tz=KST)
        base_delta = base_tf.to_timedelta()
        target_end_ts = pd.Timestamp(end, tz=KST) + base_delta
        frames: dict[str, pd.DataFrame] = {base_tf.raw: base_df}
        for target_tf in cfg.targets:
            if target_tf.raw == base_tf.raw:
                continue
            source_tf = cfg.select_source_for_target(target_tf, frames.keys())
            source_df = frames[source_tf.raw]
            resampled = resample_dataframe(source_df, source_tf, target_tf)
            if resampled.empty:
                continue
            resampled = resampled[resampled.index >= start_ts]
            if resampled.empty:
                continue
            logger.debug(
                "Aggregated %s -> %s for %s (%s rows)",
                source_tf.raw,
                target_tf.raw,
                symbol,
                len(resampled),
            )
            delta = target_tf.to_timedelta() if target_tf.unit in {"m", "d", "w"} else None
            if delta:
                valid_mask = (resampled.index + delta) <= target_end_ts
                resampled = resampled[valid_mask]
                if resampled.empty:
                    continue
            agg_payload: list[dict] = []
            for ts, row in resampled.iterrows():
                agg_payload.append(
                    {
                        "timeframe": target_tf.raw,
                        "symbol": symbol,
                        "timestamp": normalize_timestamp(ts.to_pydatetime()),
                        "opening_price": float(row["open"]),
                        "high_price": float(row["high"]),
                        "low_price": float(row["low"]),
                        "trade_price": float(row["close"]),
                        "candle_acc_trade_price": float(row["value"]),
                        "candle_acc_trade_volume": float(row["volume"]),
                    }
                )
            self._upsert_candles(session, agg_payload)
            if delta:
                rng_start = resampled.index[0].to_pydatetime()
                rng_end = resampled.index[-1].to_pydatetime() + delta
                if self._is_range_complete(session, symbol, target_tf, rng_start, rng_end):
                    if not self._range_covered(session, symbol, target_tf.raw, rng_start, rng_end):
                        self._record_range(session, symbol, target_tf.raw, rng_start, rng_end)
                        self._merge_ranges(session, symbol, target_tf.raw)
                else:
                    logger.warning(
                        "Skipping aggregated range record for %s %s [%s, %s): missing candles",
                        symbol,
                        target_tf.raw,
                        rng_start,
                        rng_end,
                    )
            frames[target_tf.raw] = resampled

    def _upsert_candles(self, session: Session, payload: list[dict]) -> None:
        if not payload:
            return
        stmt = sqlite_insert(models.OHLCV).values(payload)
        update_cols = {
            "opening_price": stmt.excluded.opening_price,
            "high_price": stmt.excluded.high_price,
            "low_price": stmt.excluded.low_price,
            "trade_price": stmt.excluded.trade_price,
            "candle_acc_trade_price": stmt.excluded.candle_acc_trade_price,
            "candle_acc_trade_volume": stmt.excluded.candle_acc_trade_volume,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["timeframe", "symbol", "timestamp"],
            set_=update_cols,
        )
        session.execute(stmt)

    def _record_range(self, session: Session, symbol: str, timeframe: str, start: datetime, end: datetime) -> None:
        start = normalize_timestamp(start)
        end = normalize_timestamp(end)
        rng = models.OHLCVRange(
            timeframe=timeframe,
            symbol=symbol,
            start_timestamp=start,
            end_timestamp=end,
        )
        session.merge(rng)
        logger.debug(
            "Recorded range %s %s [%s, %s)",
            symbol,
            timeframe,
            start,
            end,
        )

    def _merge_ranges(self, session: Session, symbol: str, timeframe: str) -> None:
        query = (
            select(models.OHLCVRange)
            .where(
                and_(models.OHLCVRange.symbol == symbol, models.OHLCVRange.timeframe == timeframe)
            )
            .order_by(models.OHLCVRange.start_timestamp.asc())
        )
        ranges = session.execute(query).scalars().all()
        if not ranges:
            return
        merged: list[tuple[datetime, datetime]] = []
        cur_start, cur_end = ranges[0].start_timestamp, ranges[0].end_timestamp
        for rng in ranges[1:]:
            if rng.start_timestamp <= cur_end:
                cur_end = max(cur_end, rng.end_timestamp)
            else:
                merged.append((cur_start, cur_end))
                cur_start, cur_end = rng.start_timestamp, rng.end_timestamp
        merged.append((cur_start, cur_end))
        session.query(models.OHLCVRange).filter(
            and_(models.OHLCVRange.symbol == symbol, models.OHLCVRange.timeframe == timeframe)
        ).delete()
        for start, end in merged:
            session.add(
                models.OHLCVRange(
                    timeframe=timeframe,
                    symbol=symbol,
                    start_timestamp=start,
                    end_timestamp=end,
                )
            )

    def _fetch_ranges(self, session: Session, symbol: str, timeframe: str) -> list[tuple[datetime, datetime]]:
        query = select(models.OHLCVRange).where(
            and_(models.OHLCVRange.symbol == symbol, models.OHLCVRange.timeframe == timeframe)
        )
        ranges = session.execute(query).scalars().all()
        return [(ensure_kst(rng.start_timestamp), ensure_kst(rng.end_timestamp)) for rng in ranges]

    def _range_covered(self, session: Session, symbol: str, timeframe: str, start: datetime, end: datetime) -> bool:
        existing = self._fetch_ranges(session, symbol, timeframe)
        missing = OHLCVRangeCalculator.subtract(existing, (start, end))
        return len(missing) == 0

    def _is_range_complete(self, session: Session, symbol: str, tf: TimeframeSpec, start: datetime, end: datetime) -> bool:
        expected = len(list(generate_expected_timestamps(start, end, tf)))
        if expected == 0:
            return False
        query = (
            select(func.count())
            .select_from(models.OHLCV)
            .where(
                and_(
                    models.OHLCV.symbol == symbol,
                    models.OHLCV.timeframe == tf.raw,
                    models.OHLCV.timestamp >= normalize_timestamp(start),
                    models.OHLCV.timestamp < normalize_timestamp(end),
                )
            )
        )
        present = session.execute(query).scalar_one()
        return present >= expected

    def _latest_range(self, session: Session, symbol: str, timeframe: str) -> models.OHLCVRange | None:
        query = (
            select(models.OHLCVRange)
            .where(
                and_(models.OHLCVRange.symbol == symbol, models.OHLCVRange.timeframe == timeframe)
            )
            .order_by(models.OHLCVRange.end_timestamp.desc())
            .limit(1)
        )
        return session.execute(query).scalar_one_or_none()


def align_timestamp(moment: datetime, timeframe: TimeframeSpec) -> datetime:
    delta = timeframe.to_timedelta()
    epoch = datetime(1970, 1, 1, tzinfo=moment.tzinfo)
    elapsed = moment - epoch
    steps = int(elapsed.total_seconds() // delta.total_seconds())
    return epoch + steps * delta


def generate_expected_timestamps(start: datetime, end: datetime, timeframe: TimeframeSpec) -> Iterator[datetime]:
    delta = timeframe.to_timedelta()
    cursor = start
    while cursor < end:
        yield cursor
        cursor += delta


def find_missing_timestamps(
    start: datetime,
    end: datetime,
    timeframe: TimeframeSpec,
    harvested: dict[datetime, dict],
) -> list[tuple[datetime, datetime]]:
    missing: list[tuple[datetime, datetime]] = []
    delta = timeframe.to_timedelta()
    cursor = start
    gap_start: datetime | None = None
    while cursor < end:
        if cursor not in harvested:
            if gap_start is None:
                gap_start = cursor
        else:
            if gap_start is not None:
                missing.append((gap_start, cursor))
                gap_start = None
        cursor += delta
    if gap_start is not None:
        missing.append((gap_start, end))
    return missing


def interpolate_candles(
    start: datetime,
    end: datetime,
    timeframe: TimeframeSpec,
    harvested: dict[datetime, dict],
) -> list[dict]:
    delta = timeframe.to_timedelta()
    cursor = start
    synthesized: list[dict] = []
    last_known = None
    sorted_keys = sorted(k for k in harvested.keys() if k < start)
    if sorted_keys:
        last_known = harvested[sorted_keys[-1]]
    while cursor < end:
        if cursor in harvested:
            last_known = harvested[cursor]
            cursor += delta
            continue
        if last_known is None:
            cursor += delta
            continue
        open_price = last_known["trade_price"]
        close_price = last_known["trade_price"]
        candle = {
            "symbol": last_known["symbol"],
            "timeframe": timeframe.raw,
            "timestamp": cursor,
            "opening_price": open_price,
            "high_price": max(open_price, close_price),
            "low_price": min(open_price, close_price),
            "trade_price": close_price,
            "candle_acc_trade_price": 0.0,
            "candle_acc_trade_volume": 0.0,
        }
        synthesized.append(candle)
        cursor += delta
    return synthesized


def resample_dataframe(
    df: pd.DataFrame,
    base_tf: TimeframeSpec,
    target_tf: TimeframeSpec,
) -> pd.DataFrame:
    if df.empty:
        return df
    rule = target_tf.pandas_freq
    agg = df.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "value": "sum",
        }
    )
    agg = agg.dropna(subset=["open", "close"])
    return agg
