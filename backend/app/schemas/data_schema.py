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

	
