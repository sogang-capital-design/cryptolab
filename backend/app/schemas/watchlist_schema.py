from pydantic import BaseModel, Field
from typing import List

class WatchlistCreateRequest(BaseModel):
    coin_symbols: List[str] = Field(..., min_items=0)

class WatchlistResponse(BaseModel):
    coin_symbols: List[str]

