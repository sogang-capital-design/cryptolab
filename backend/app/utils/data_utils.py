import os
from typing import TYPE_CHECKING, List, Tuple

import pandas as pd
import json
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
        # on chain 데이터는 아직 실시간을 지원하지 않으므로 임시로 2025-06-30로 고정
        end = pd.Timestamp("2025-06-30 23:00:00")
        data_info.append((coin_symbol, pd.Timestamp(start), pd.Timestamp(end)))
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

def get_onchain_df(coin_symbol: str, timeframe: int) -> pd.DataFrame:
    data_path = _get_data_path()
    onchain_data_path = os.path.join(data_path, 'onchain')
    specific_data_path = os.path.join(onchain_data_path, f'{coin_symbol}_{timeframe}m_20240101_20250630.csv')
    common_data_path = os.path.join(onchain_data_path, f'common_{timeframe}m_20240101_20250630.csv')
    specific_df = pd.read_csv(specific_data_path, parse_dates=["hour"])
    common_df = pd.read_csv(common_data_path, parse_dates=["hour"])
    
    common_df['hour'] = common_df['hour'].dt.tz_localize(None)
    common_df = common_df.set_index("hour").sort_index()
    specific_df['hour'] = specific_df['hour'].dt.tz_localize(None)
    specific_df = specific_df.set_index("hour").sort_index()

    data_df = pd.concat([specific_df, common_df], axis=1)
    data_df = data_df.rename(columns={"price": "price_usd"})
    data_df.index = pd.to_datetime(data_df.index) + pd.Timedelta(hours=9)  # KST로 변환
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