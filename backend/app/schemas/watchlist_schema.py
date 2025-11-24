from pydantic import BaseModel, Field
from typing import List

class WatchlistCreateRequest(BaseModel):
    coin_symbols: List[str] = []

class WatchlistResponse(BaseModel):
    coin_symbols: List[str]

