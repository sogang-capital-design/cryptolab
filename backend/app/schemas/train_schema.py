from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class TrainRequest(BaseModel):
	model_name: str
	param_name: str
	coin_symbol: str
	timeframe: int
	start: datetime
	end: datetime
	hyperparams: Dict[str, Any] = Field(default_factory=dict)

class TrainResponse(BaseModel):
	task_id: str

class TrainTaskResponse(BaseModel):
	task_id: str
	status: str