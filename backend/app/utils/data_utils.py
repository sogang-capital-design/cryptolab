import os
import requests
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Tuple
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
    """
    온체인 데이터가 있는 코인 목록을 반환합니다.
    DB 대신 파일 시스템에서 사용 가능한 코인을 확인합니다.
    """
    data_path = _get_data_path()
    onchain_data_path = os.path.join(data_path, 'onchain')

    data_info: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []

    # 온체인 데이터 파일에서 코인 목록 추출
    if os.path.exists(onchain_data_path):
        for filename in os.listdir(onchain_data_path):
            # USDT는 제외하고, _60m_20240101_20250630.csv 패턴만 포함
            if filename.endswith('_60m_20240101_20250630.csv') and filename != 'USDT_60m_20240101_20250630.csv':
                coin_symbol = filename.split('_')[0]
                # 고정된 시간 범위 (온체인 데이터 파일명에서 추출)
                start = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
                end = pd.Timestamp("2025-06-30 23:00:00", tz="UTC")
                data_info.append((coin_symbol, start, end))

    # 정렬하여 반환
    data_info.sort(key=lambda x: x[0])
    return data_info

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
    data_path = _get_data_path()
    ohlcv_data_path = os.path.join(data_path, 'ohlcv')
    ohlcv_file_path = os.path.join(ohlcv_data_path, f'binance_ohlcv_1h_{coin_symbol}USDT_20240101_20250630_utc.csv')
    ohlcv_df = pd.read_csv(ohlcv_file_path, parse_dates=["datetime_utc"])
    ohlcv_df['price'] = ohlcv_df['close']

    onchain_data_path = os.path.join(data_path, 'onchain')
    cur_onchain_data_path = os.path.join(onchain_data_path, f'{coin_symbol}_60m_20240101_20250630.csv')
    usdt_onchain_data_path = os.path.join(onchain_data_path, f'USDT_60m_20240101_20250630.csv')
    cur_onchain_df = pd.read_csv(cur_onchain_data_path, parse_dates=["hour"])
    usdt_onchain_df = pd.read_csv(usdt_onchain_data_path, parse_dates=["hour"])
    
    ohlcv_df["datetime_utc"] = pd.to_datetime(ohlcv_df["datetime_utc"], utc=True)
    ohlcv_df = ohlcv_df.set_index("datetime_utc").sort_index()
    usdt_onchain_df["hour"] = pd.to_datetime(usdt_onchain_df["hour"], utc=True)
    usdt_onchain_df = usdt_onchain_df.set_index("hour").sort_index()
    cur_onchain_df["hour"] = pd.to_datetime(cur_onchain_df["hour"], utc=True)
    cur_onchain_df = cur_onchain_df.set_index("hour").sort_index()
    usdt_onchain_df.columns = [f"usdt_{col}" for col in usdt_onchain_df.columns]

    data_df = (
        ohlcv_df
        .merge(cur_onchain_df, left_index=True, right_index=True, how="inner")
        .merge(usdt_onchain_df, left_index=True, right_index=True, how="inner")
    )
    return data_df

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
