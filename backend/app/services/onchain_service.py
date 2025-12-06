from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import and_, select, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db import models
from app.services.ohlcv_service import (
    KST,
    ConfigurationError,
    OHLCVRangeCalculator,
    SymbolTimeframeConfig,
    align_timestamp,
    ensure_kst,
    find_missing_timestamps,
    generate_expected_timestamps,
    load_symbol_configs,
    normalize_timestamp,
)

logger = logging.getLogger(__name__)


class DuneAPIError(RuntimeError):
    """Raised when Dune API interactions fail."""


class DuneClient:
    def __init__(self, api_key: str, base_url: str = "https://api.dune.com/api/v1", poll_interval: float = 2.0, timeout: float = 180.0) -> None:
        if not api_key:
            raise ConfigurationError("DUNE_API_KEY must be configured for onchain ingestion.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.poll_interval = poll_interval
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-dune-api-key": self.api_key}

    def fetch(self, query_id: int, params: dict[str, str]) -> list[dict]:
        execution_id = self._execute(query_id, params)
        self._wait_for_completion(execution_id)
        return self._fetch_results(execution_id)

    def _execute(self, query_id: int, params: dict[str, str]) -> str:
        url = f"{self.base_url}/query/{query_id}/execute"
        response = self.session.post(url, headers=self._headers, json={"query_parameters": params}, timeout=30)
        if response.status_code >= 400:
            raise DuneAPIError(f"Failed to execute Dune query {query_id}: {response.text}")
        payload = response.json()
        execution_id = payload.get("execution_id")
        if not execution_id:
            raise DuneAPIError(f"Missing execution_id in Dune response for query {query_id}.")
        return execution_id

    def _wait_for_completion(self, execution_id: str) -> None:
        url = f"{self.base_url}/execution/{execution_id}/status"
        start_time = time.monotonic()
        while True:
            response = self.session.get(url, headers=self._headers, timeout=15)
            if response.status_code >= 400:
                raise DuneAPIError(f"Failed to fetch execution status for {execution_id}: {response.text}")
            payload = response.json()
            state = payload.get("state")
            if state == "QUERY_STATE_COMPLETED":
                return
            if state in {"QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_ERRORED"}:
                raise DuneAPIError(f"Dune execution {execution_id} failed with state {state}.")
            if time.monotonic() - start_time > self.timeout:
                raise DuneAPIError(f"Timed out waiting for Dune execution {execution_id} to complete.")
            time.sleep(self.poll_interval)

    def _fetch_results(self, execution_id: str) -> list[dict]:
        url = f"{self.base_url}/execution/{execution_id}/results"
        response = self.session.get(url, headers=self._headers, timeout=30)
        if response.status_code >= 400:
            raise DuneAPIError(f"Failed to fetch results for execution {execution_id}: {response.text}")
        payload = response.json()
        result = payload.get("result") or {}
        rows = result.get("rows")
        if rows is None:
            raise DuneAPIError(f"Missing rows in Dune result for execution {execution_id}.")
        return rows


class OnchainIngestService:
    def __init__(self) -> None:
        self.config_path = os.getenv("OHLCV_CONFIG_PATH", "config/ohlcv_settings.yml")
        default_targets_env = os.getenv("DEFAULT_TARGET_TIMEFRAMES", "60m,240m,1d")
        default_targets = [item.strip() for item in default_targets_env.split(",") if item.strip()]
        self.symbol_configs = load_symbol_configs(self.config_path, default_targets)
        self._symbol_by_simple = {cfg.simple_symbol.upper(): cfg for cfg in self.symbol_configs}

        self.collect_start = self._parse_collect_start(os.getenv("OHLCV_COLLECT_START"))
        retry_limit = int(os.getenv("OHLCV_RETRY_LIMIT", "1"))
        self.max_attempts = retry_limit if retry_limit > 0 else 1
        self.data_dir = Path(os.getenv("ONCHAIN_DATA_DIR", "data/onchain"))
        self.dune_client = DuneClient(api_key=os.getenv("DUNE_API_KEY", ""))
        self._bootstrap_done = False
        self.execution_offset_seconds = int(os.getenv("OHLCV_EXECUTION_OFFSET_SECONDS", "0"))

    def _parse_collect_start(self, raw: str | None) -> datetime:
        if not raw:
            raise ConfigurationError("OHLCV_COLLECT_START must be set (e.g., '2024-01-01T00:00:00').")
        try:
            dt = datetime.fromisoformat(raw)
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError(f"Invalid OHLCV_COLLECT_START: '{raw}'") from exc
        return ensure_kst(dt)

    def collect_latest(self, session: Session) -> None:
        request_time = self._current_request_time()
        self._bootstrap_from_csv(session)
        for cfg in self.symbol_configs:
            base = cfg.base
            start = align_timestamp(self.collect_start, base)
            target_end = self._derive_target_end(session, cfg, request_time)
            if target_end is None or target_end <= start:
                continue
            existing_ranges = self._fetch_ranges(session, cfg.symbol, base.raw)
            missing = OHLCVRangeCalculator.subtract(existing_ranges, (start, target_end))
            for missing_start, missing_end in missing:
                payload = self._harvest_range(cfg, missing_start, missing_end)
                if not payload:
                    continue
                self._persist_onchain(session, payload)
                range_start = payload[0]["hour"]
                range_end = payload[-1]["hour"] + base.to_timedelta()
                if self._is_range_complete(session, cfg, range_start, range_end):
                    if not self._range_covered(session, cfg.symbol, base.raw, range_start, range_end):
                        self._record_range(session, cfg.symbol, base.raw, range_start, range_end)
                        self._merge_ranges(session, cfg.symbol, base.raw)
                else:
                    logger.warning(
                        "Skipping onchain range record for %s [%s, %s): missing rows",
                        cfg.symbol,
                        range_start,
                        range_end,
                    )
            session.commit()

    def _current_request_time(self) -> datetime:
        now = datetime.now(tz=KST)
        if self.execution_offset_seconds > 0:
            now -= timedelta(seconds=self.execution_offset_seconds)
        return now

    def _bootstrap_from_csv(self, session: Session) -> None:
        if self._bootstrap_done or not self.data_dir.exists():
            self._bootstrap_done = True
            return
        csv_files = sorted(self.data_dir.glob("*.csv"))
        for path in csv_files:
            parts = path.stem.split("_")
            if len(parts) < 2:
                continue
            simple_symbol = parts[0].upper()
            timeframe = parts[1]
            cfg = self._symbol_by_simple.get(simple_symbol)
            if not cfg or cfg.base.raw != timeframe:
                continue
            try:
                self._ingest_csv_file(session, cfg, path)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to bootstrap onchain CSV %s: %s", path, exc)
        session.commit()
        self._bootstrap_done = True

    def _ingest_csv_file(self, session: Session, cfg: SymbolTimeframeConfig, path: Path) -> None:
        df = pd.read_csv(path)
        if df.empty:
            return
        if "hour" not in df.columns:
            raise ConfigurationError(f"Onchain CSV '{path}' missing 'hour' column.")
        df["hour"] = pd.to_datetime(df["hour"], utc=True, errors="coerce")
        df = df.dropna(subset=["hour"])
        if df.empty:
            return
        df["hour"] = df["hour"].dt.tz_convert(KST)
        payload: list[dict] = []
        for _, row in df.iterrows():
            hour = ensure_kst(row["hour"].to_pydatetime())
            payload.append(self._build_row(cfg.symbol, hour, row.to_dict()))
        self._persist_onchain(session, payload)
        delta = cfg.base.to_timedelta()
        range_start = ensure_kst(df["hour"].min().to_pydatetime())
        range_end = ensure_kst(df["hour"].max().to_pydatetime()) + delta
        if self._is_range_complete(session, cfg, range_start, range_end):
            if not self._range_covered(session, cfg.symbol, cfg.base.raw, range_start, range_end):
                self._record_range(session, cfg.symbol, cfg.base.raw, range_start, range_end)
                self._merge_ranges(session, cfg.symbol, cfg.base.raw)

    def _harvest_range(self, cfg: SymbolTimeframeConfig, start: datetime, end: datetime) -> list[dict]:
        harvested: dict[datetime, dict] = {}
        attempts = 0
        while attempts < self.max_attempts:
            attempts += 1
            rows = self._fetch_from_dune(cfg, start, end)
            for row in rows:
                hour = self._parse_hour(row.get("hour"))
                if hour is None or hour < start or hour >= end:
                    continue
                harvested[hour] = row
            missing = find_missing_timestamps(start, end, cfg.base, harvested)
            if not missing:
                break
            if attempts < self.max_attempts:
                logger.info(
                    "Retrying Dune fetch for %s due to missing intervals: %s",
                    cfg.symbol,
                    missing,
                )
        if not harvested:
            logger.warning("No onchain data fetched for %s between %s and %s", cfg.symbol, start, end)
            return []
        payload = [self._build_row(cfg.symbol, ts, harvested[ts]) for ts in sorted(harvested)]
        return payload

    def _fetch_from_dune(self, cfg: SymbolTimeframeConfig, start: datetime, end: datetime) -> list[dict]:
        params = self._build_query_params(cfg, start, end)
        query_id = 6296410 if cfg.token_address is None else 6295814
        try:
            return self.dune_client.fetch(query_id, params)
        except DuneAPIError as exc:
            logger.error("Dune fetch failed for %s: %s", cfg.symbol, exc)
            return []

    def _build_query_params(self, cfg: SymbolTimeframeConfig, start: datetime, end: datetime) -> dict[str, str]:
        start_utc = ensure_kst(start).astimezone(timezone.utc)
        end_utc = ensure_kst(end).astimezone(timezone.utc)
        params = {
            "start_ts": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "end_ts": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if cfg.token_address:
            params["token_address"] = cfg.token_address
        return params

    def _build_row(self, symbol: str, hour: datetime, row: dict) -> dict:
        return {
            "symbol": symbol,
            "hour": normalize_timestamp(hour),
            "total_volume": float(row.get("total_volume", 0.0)),
            "total_tx_count": float(row.get("total_tx_count", 0.0)),
            "cex_inflow": float(row.get("cex_inflow", 0.0)),
            "cex_outflow": float(row.get("cex_outflow", 0.0)),
            "cex_tx_count": float(row.get("cex_tx_count", 0.0)),
            "dex_inflow": float(row.get("dex_inflow", 0.0)),
            "dex_outflow": float(row.get("dex_outflow", 0.0)),
            "dex_tx_count": float(row.get("dex_tx_count", 0.0)),
            "inst_inflow": float(row.get("inst_inflow", 0.0)),
            "inst_outflow": float(row.get("inst_outflow", 0.0)),
            "inst_tx_count": float(row.get("inst_tx_count", 0.0)),
        }

    def _parse_hour(self, raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            cleaned = raw.replace(" UTC", "").replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.debug("Unable to parse hour value '%s'", raw)
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return ensure_kst(dt)

    def _persist_onchain(self, session: Session, payload: list[dict]) -> None:
        if not payload:
            return
        stmt = sqlite_insert(models.Onchain).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["hour", "symbol"],
            set_={
                "total_volume": stmt.excluded.total_volume,
                "total_tx_count": stmt.excluded.total_tx_count,
                "cex_inflow": stmt.excluded.cex_inflow,
                "cex_outflow": stmt.excluded.cex_outflow,
                "cex_tx_count": stmt.excluded.cex_tx_count,
                "dex_inflow": stmt.excluded.dex_inflow,
                "dex_outflow": stmt.excluded.dex_outflow,
                "dex_tx_count": stmt.excluded.dex_tx_count,
                "inst_inflow": stmt.excluded.inst_inflow,
                "inst_outflow": stmt.excluded.inst_outflow,
                "inst_tx_count": stmt.excluded.inst_tx_count,
            },
        )
        session.execute(stmt)

    def _record_range(self, session: Session, symbol: str, timeframe: str, start: datetime, end: datetime) -> None:
        start = normalize_timestamp(start)
        end = normalize_timestamp(end)
        rng = models.OnchainRange(
            timeframe=timeframe,
            symbol=symbol,
            start_timestamp=start,
            end_timestamp=end,
        )
        session.merge(rng)

    def _merge_ranges(self, session: Session, symbol: str, timeframe: str) -> None:
        query = (
            select(models.OnchainRange)
            .where(and_(models.OnchainRange.symbol == symbol, models.OnchainRange.timeframe == timeframe))
            .order_by(models.OnchainRange.start_timestamp.asc())
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
        session.query(models.OnchainRange).filter(
            and_(models.OnchainRange.symbol == symbol, models.OnchainRange.timeframe == timeframe)
        ).delete()
        for start, end in merged:
            session.add(
                models.OnchainRange(
                    timeframe=timeframe,
                    symbol=symbol,
                    start_timestamp=start,
                    end_timestamp=end,
                )
            )

    def _fetch_ranges(self, session: Session, symbol: str, timeframe: str) -> list[tuple[datetime, datetime]]:
        query = select(models.OnchainRange).where(
            and_(models.OnchainRange.symbol == symbol, models.OnchainRange.timeframe == timeframe)
        )
        ranges = session.execute(query).scalars().all()
        return [(ensure_kst(rng.start_timestamp), ensure_kst(rng.end_timestamp)) for rng in ranges]

    def _range_covered(self, session: Session, symbol: str, timeframe: str, start: datetime, end: datetime) -> bool:
        existing = self._fetch_ranges(session, symbol, timeframe)
        target = (ensure_kst(start), ensure_kst(end))
        missing = OHLCVRangeCalculator.subtract(existing, target)
        return len(missing) == 0

    def _is_range_complete(self, session: Session, cfg: SymbolTimeframeConfig, start: datetime, end: datetime) -> bool:
        expected = len(list(generate_expected_timestamps(start, end, cfg.base)))
        if expected == 0:
            return False
        query = (
            select(func.count())
            .select_from(models.Onchain)
            .where(
                and_(
                    models.Onchain.symbol == cfg.symbol,
                    models.Onchain.hour >= normalize_timestamp(start),
                    models.Onchain.hour < normalize_timestamp(end),
                )
            )
        )
        present = session.execute(query).scalar_one()
        return present >= expected

    def _derive_target_end(self, session: Session, cfg: SymbolTimeframeConfig, request_time: datetime) -> datetime | None:
        query = (
            select(func.max(models.OHLCVRange.end_timestamp))
            .where(and_(models.OHLCVRange.symbol == cfg.symbol, models.OHLCVRange.timeframe == cfg.base.raw))
        )
        latest_end = session.execute(query).scalar_one_or_none()
        delta = cfg.base.to_timedelta()
        if latest_end is not None:
            latest_end = ensure_kst(latest_end)
            candidate = latest_end - delta
            if candidate <= self.collect_start:
                return None
            return align_timestamp(candidate, cfg.base)
        candidate = align_timestamp(request_time, cfg.base) - delta
        if candidate <= self.collect_start:
            return None
        return align_timestamp(candidate, cfg.base)
