from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class DecisionRequest(BaseModel):
	model_name: str
	current_time: datetime
	cash_balance: float
	coin_balance: float
	hyperparams: Dict[str, Any] = Field(default_factory=dict)
	
class DecisionResponse(BaseModel):
	action: int
	amount: float