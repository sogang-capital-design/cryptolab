from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

class CoinListResponse(BaseModel):
    available_coin_symbols: List[str]

class CoinInfoRequest(BaseModel):
    coin_symbol: str

class CoinInfoResponse(BaseModel):
    coin_symbol: str
    available_start: datetime
    available_end: datetime

class OHLCVRequest(BaseModel):
    coin_symbol: str
    start_time: datetime
    end_time: datetime
    interval: str = Field(default="1h", description="Binance interval (e.g., '1m', '5m', '1h', '1d')")

class OHLCVDataPoint(BaseModel):
    datetime_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int
    price: float

class OHLCVResponse(BaseModel):
    coin_symbol: str
    interval: str
    data: List[OHLCVDataPoint]


