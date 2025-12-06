import os
import requests
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Tuple
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()


import pandas as pd
import json
from dune_client.types import QueryParameter
from dune_client.client import DuneClient
from dune_client.query import QueryBase
from filelock import FileLock

from sqlalchemy import func, select

if TYPE_CHECKING:
    from app.services.ohlcv_service import OHLCVIngestService

_ingest_service: "OHLCVIngestService | None" = None

KST = ZoneInfo("Asia/Seoul")



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
    """Return available onchain coin ranges from the database."""
    from app.db.database import SessionLocal
    from app.db import models

    session = SessionLocal()
    try:
        query = (
            select(
                models.OnchainRange.symbol,
                func.min(models.OnchainRange.start_timestamp),
                func.max(models.OnchainRange.end_timestamp),
            )
            .group_by(models.OnchainRange.symbol)
        )
        rows = session.execute(query).all()
    finally:
        session.close()

    info: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
    for symbol, start, end in rows:
        if not start or not end:
            continue
        simple_symbol = symbol.split("-", 1)[-1]
        start_ts = pd.Timestamp(start).tz_localize(KST).tz_convert("UTC")
        end_ts = pd.Timestamp(end).tz_localize(KST).tz_convert("UTC")
        info.append((simple_symbol, start_ts, end_ts))
    info.sort(key=lambda x: x[0])
    return info

def get_model_meta_info(model_name: str, coin_symbol: str, timeframe: int) -> dict:
    data_path = _get_data_path()
    model_meta_path = os.path.join(data_path, 'meta', 'model_stats.json')
    
    with open(model_meta_path, "r") as f:
        meta_info = json.load(f)

    key = f"{coin_symbol}"
    try:
        return meta_info[model_name][key]
    except KeyError:
        raise KeyError(f"Meta info not found for model={model_name}, key={key}")

def get_score_meta_info() -> dict:
    data_path = _get_data_path()
    score_meta_path = os.path.join(data_path, 'meta', 'score_stats.json')
    
    with open(score_meta_path, "r") as f:
        meta_info = json.load(f)

    return meta_info

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

def get_total_df(coin_symbol: str) -> pd.DataFrame:
    from app.db.database import SessionLocal
    from app.db import models

    session = SessionLocal()
    try:
        bin_symbol = f"{coin_symbol.upper()}USDT"
        bin_rows = (
            session.execute(
                select(models.BinanceOHLCV)
                .where(models.BinanceOHLCV.symbol == bin_symbol)
                .order_by(models.BinanceOHLCV.timestamp.asc())
            )
            .scalars()
            .all()
        )
        if not bin_rows:
            raise ValueError(f"No Binance OHLCV data for {bin_symbol}")

        target_symbol = f"KRW-{coin_symbol.upper()}"
        cur_rows = (
            session.execute(
                select(models.Onchain)
                .where(models.Onchain.symbol == target_symbol)
                .order_by(models.Onchain.hour.asc())
            )
            .scalars()
            .all()
        )
        if not cur_rows:
            raise ValueError(f"No onchain data for {target_symbol}")

        usdt_rows = (
            session.execute(
                select(models.Onchain)
                .where(models.Onchain.symbol == "KRW-USDT")
                .order_by(models.Onchain.hour.asc())
            )
            .scalars()
            .all()
        )
        if not usdt_rows:
            raise ValueError("No onchain data for KRW-USDT")
    finally:
        session.close()

    ohlcv_df = _binance_rows_to_df(bin_rows)
    cur_onchain_df = _onchain_rows_to_df(cur_rows)
    usdt_onchain_df = _onchain_rows_to_df(usdt_rows)
    usdt_onchain_df.columns = [f"usdt_{col}" for col in usdt_onchain_df.columns]

    data_df = (
        ohlcv_df
        .merge(cur_onchain_df, left_index=True, right_index=True, how="inner")
        .merge(usdt_onchain_df, left_index=True, right_index=True, how="inner")
    )
    return data_df


def _kst_naive_to_utc(moment: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(moment)
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        ts = ts.tz_localize(KST)
    else:
        ts = ts.tz_convert(KST)
    return ts.tz_convert("UTC")


def _binance_rows_to_df(rows) -> pd.DataFrame:
    records: list[dict] = []
    for row in rows:
        records.append(
            {
                "datetime_utc": _kst_naive_to_utc(row.timestamp),
                "open": float(row.open_price),
                "high": float(row.high_price),
                "low": float(row.low_price),
                "close": float(row.close_price),
                "volume": float(row.volume),
                "trade_count": int(row.trade_count),
                "price": float(row.close_price),
            }
        )
    df = pd.DataFrame(records)
    if df.empty:
        return df
    return df.set_index("datetime_utc").sort_index()


def _onchain_rows_to_df(rows) -> pd.DataFrame:
    records: list[dict] = []
    for row in rows:
        records.append(
            {
                "datetime_utc": _kst_naive_to_utc(row.hour),
                "total_volume": float(row.total_volume),
                "total_tx_count": float(row.total_tx_count),
                "cex_inflow": float(row.cex_inflow),
                "cex_outflow": float(row.cex_outflow),
                "cex_tx_count": float(row.cex_tx_count),
                "dex_inflow": float(row.dex_inflow),
                "dex_outflow": float(row.dex_outflow),
                "dex_tx_count": float(row.dex_tx_count),
                "inst_inflow": float(row.inst_inflow),
                "inst_outflow": float(row.inst_outflow),
                "inst_tx_count": float(row.inst_tx_count),
            }
        )
    df = pd.DataFrame(records)
    if df.empty:
        return df
    return df.set_index("datetime_utc").sort_index()

def fetch_binance_klines(symbol: str, start_dt_utc: datetime, end_dt_utc: datetime,
                         interval: str = "1h", limit: int = 1000, sleep_sec: float = 0.12) -> pd.DataFrame:
    url = f"https://api.binance.com/api/v3/klines"

    all_rows = []
    # Binance는 startTime, endTime을 ms 단위로 받음
    start_ms = int(start_dt_utc.timestamp() * 1000)
    end_ms   = int(end_dt_utc.timestamp() * 1000)

    cur_start = start_ms

    while True:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur_start,
            "endTime": end_ms,
            "limit": limit
        }

        resp = requests.get(url, params=params)
        if resp.status_code != 200:
            print(f"[{symbol}] 요청 실패 (status {resp.status_code}): {resp.text}")
            break

        data = resp.json()
        if not data:
            break

        all_rows.extend(data)
        last_open_time_ms = data[-1][0]
        next_start = last_open_time_ms + 60 * 60 * 1000

        if next_start > end_ms:
            break

        cur_start = next_start
        time.sleep(sleep_sec)

    if not all_rows:
        print(f"[{symbol}] 수집된 데이터가 없습니다.")
        return pd.DataFrame()
    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trade_count",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore"
    ]
    df = pd.DataFrame(all_rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    mask = (df["open_time"] >= start_dt_utc) & (df["open_time"] < end_dt_utc)
    df = df.loc[mask].copy()

    numeric_cols = ["open", "high", "low", "close",
                    "volume", "quote_volume", "trade_count"]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.sort_values("open_time", inplace=True)
    df.set_index("open_time", inplace=True)
    df.index.name = "datetime_utc"
    df = df[["open", "high", "low", "close", "volume", "trade_count"]]
    df['price'] = df['close']
    return df

TOKEN_ADDR = {
    "LINK":  "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    "UNI":   "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "AAVE":  "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
    "1INCH": "0x111111111117dC0aa78b770fA6A738034120C302",
    "SAND":  "0x3845badAde8e6dFF049820680d1F14bD3903a5d0",
    "PEPE":  "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
    "SHIB":  "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
    "USDT":  "0xdac17f958d2ee523a2206206994597c13d831ec7"
}
def fetch_dune_query_result(coin_symbol: str, start_ts: str, end_ts: str) -> pd.DataFrame:
    # 락 파일 경로 생성
    data_path = _get_data_path()
    dune_data_path = os.path.join(data_path, 'dune_query')
    os.makedirs(dune_data_path, exist_ok=True)

    cache_key = f"{coin_symbol}_{start_ts.replace(' ', '_').replace(':', '-')}_{end_ts.replace(' ', '_').replace(':', '-')}"
    lock_file = os.path.join(dune_data_path, f"{cache_key}.lock")

    # 파일 락을 사용하여 동시 요청 방지
    with FileLock(lock_file, timeout=60):
        # 락을 획득한 후 다시 캐시 확인 (다른 worker가 이미 생성했을 수 있음)
        if (df := _load_dune_query_result(coin_symbol, start_ts, end_ts)) is not None:
            return df

        # 캐시가 없으면 API 호출
        dune = DuneClient()

        if coin_symbol == 'ETH':
            query = QueryBase(
                name="ETH Query",
                query_id=6296410,
                params=[
                    QueryParameter.text_type(name="start_ts", value=start_ts),
                    QueryParameter.text_type(name="end_ts", value=end_ts),
                ],
            )
        elif coin_symbol in TOKEN_ADDR:
            token_address = TOKEN_ADDR[coin_symbol]
            query = QueryBase(
                name=f"{coin_symbol} Query",
                query_id=6295814,
                params=[
                    QueryParameter.text_type(name="token_address", value=token_address),
                    QueryParameter.text_type(name="start_ts", value=start_ts),
                    QueryParameter.text_type(name="end_ts", value=end_ts),
                ],
            )

        df = dune.run_query_dataframe(query)
        df['hour'] = pd.to_datetime(df['hour'], utc=True)
        df = df.set_index('hour').sort_index()
        print(f"[Dune API] Fetched {coin_symbol} data from {start_ts} to {end_ts}")
        _save_dune_query_result(coin_symbol, df, start_ts, end_ts)

        return df

def _load_dune_query_result(coin_symbol: str, start_ts: str, end_ts: str) -> pd.DataFrame | None:
    data_path = _get_data_path()
    dune_data_path = os.path.join(data_path, 'dune_query')
    file_path = os.path.join(dune_data_path, f'dune_{coin_symbol}_{start_ts.replace(" ", "_").replace(":", "-")}_{end_ts.replace(" ", "_").replace(":", "-")}.csv')
    if os.path.exists(file_path):
        df = pd.read_csv(file_path, parse_dates=["hour"])
        df['hour'] = pd.to_datetime(df['hour'], utc=True)
        df = df.set_index('hour').sort_index()
        return df
    return None

def _save_dune_query_result(coin_symbol: str, df: pd.DataFrame, start_ts: str, end_ts: str) -> None:
    data_path = _get_data_path()
    dune_data_path = os.path.join(data_path, 'dune_query')
    os.makedirs(dune_data_path, exist_ok=True)
    file_path = os.path.join(dune_data_path, f'dune_{coin_symbol}_{start_ts.replace(" ", "_").replace(":", "-")}_{end_ts.replace(" ", "_").replace(":", "-")}.csv')
    df.to_csv(file_path)

def get_total_df_online(coin_symbol: str, start_time: pd.Timestamp, end_time: pd.Timestamp) -> pd.DataFrame:
    # assert utc timezone
    assert start_time.tzinfo is not None and start_time.tzinfo.utcoffset(start_time) == pd.Timedelta(0)
    assert end_time.tzinfo is not None and end_time.tzinfo.utcoffset(end_time) == pd.Timedelta(0)
    ohlcv_df = fetch_binance_klines(
        symbol=f"{coin_symbol}USDT",
        start_dt_utc=start_time.to_pydatetime(),
        end_dt_utc=end_time.to_pydatetime(),
        interval="1h"
    )
    onchain_df = fetch_dune_query_result(
        coin_symbol,
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        end_time.strftime("%Y-%m-%d %H:%M:%S")
    )
    usdt_onchain_df = fetch_dune_query_result(
        "USDT",
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        end_time.strftime("%Y-%m-%d %H:%M:%S")
    )
    usdt_onchain_df.columns = [f"usdt_{col}" for col in usdt_onchain_df.columns]
    
    data_df = (
        ohlcv_df
        .merge(onchain_df, left_index=True, right_index=True, how="inner")
        .merge(usdt_onchain_df, left_index=True, right_index=True, how="inner")
    )
    return data_df

def get_feature_texts(feature_type: str) -> dict:
    data_path = _get_data_path()
    feature_texts_path = os.path.join(data_path, 'feature_texts', f'{feature_type}_feature_texts.json')
    feature_texts = json.load(open(feature_texts_path, 'r'))
    return feature_texts

def get_prompt(prompt_type: str) -> str:
    data_path = _get_data_path()
    prompt_path = os.path.join(data_path, 'prompts', f'{prompt_type}_prompt.txt')
    with open(prompt_path, 'r', encoding='utf-8') as f:
        prompt = f.read()
    return prompt
