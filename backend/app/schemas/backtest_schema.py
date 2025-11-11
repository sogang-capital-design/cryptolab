from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class BacktestRequest(BaseModel):
	model_name: str
	param_name: str
	coin_symbol: str
	timeframe: int
	start: datetime
	end: datetime

class BacktestResponse(BaseModel):
	task_id: str

class BacktestTaskResponse(BaseModel):
	task_id: str
	status: str
	results: Dict[str, Any] = Field(default_factory=dict)
