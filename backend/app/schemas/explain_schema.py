from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

class ExplainRequest(BaseModel):
	model_name: str
	param_name: str
	coin_symbol: str
	timeframe: int
	train_start: datetime
	train_end: datetime
	inference_time: datetime

class ExplainResponse(BaseModel):
    task_id: str

class SimilarChartResult(BaseModel):
	timestamp: datetime
	similarity: float
    
class ExplainResult(BaseModel):
	prediction: float
	shap_values: Dict[str, float]
	feature_values: Dict[str, float]
	similar_charts: List[SimilarChartResult]
	explanation_text: str
    
class ExplainTaskResponse(BaseModel):
	task_id: str
	status: str
	results: Optional[ExplainResult] = None


