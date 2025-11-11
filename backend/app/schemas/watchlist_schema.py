from pydantic import BaseModel, Field
from typing import List

class WatchlistCreateRequest(BaseModel):
    symbols: List[str] = Field(..., min_items=5, max_items=5)

class WatchlistResponse(BaseModel):
    symbols: List[str]

