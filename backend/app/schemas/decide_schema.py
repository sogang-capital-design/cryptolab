from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class DecisionRequest(BaseModel):
	model_name: str
	param_name: str
	coin_symbol: str
	timeframe: int
	inference_time: datetime
	cash_balance: float
	coin_balance: float
	
class DecisionResponse(BaseModel):
	action: int
	amount: float
	logit : Optional[float] = None