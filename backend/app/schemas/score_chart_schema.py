from datetime import datetime
from typing import Dict, Optional
from pydantic import BaseModel, Field

class ScoreChartRequest(BaseModel):
    coin_symbol: str
    timeframe: int
    inference_time: datetime
    history_window: int = Field(default=120, ge=24)

class ScoreChartResponse(BaseModel):
    task_id: str

class ScoreWithExplanation(BaseModel):
    score: float
    explanation: str

class ScoreChartTaskResponse(BaseModel):
    task_id: str
    status: str
    results: Optional[Dict[str, ScoreWithExplanation]] = None

