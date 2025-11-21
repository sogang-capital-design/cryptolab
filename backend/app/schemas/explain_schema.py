from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

# Explain Model Schema
class ExplainModelRequest(BaseModel):
	coin_symbol: str
	timeframe: int
	inference_time: datetime

class ExplainModelResponse(BaseModel):
    task_id: str

class ReferenceChartResult(BaseModel):
	timestamp: datetime
	similarity: float
    
class ExplainModelResult(BaseModel):
	prediction_percentile: float
	recommendation: str
	shap_values: Dict[str, float]
	feature_values: Dict[str, float]
	reference_charts: List[ReferenceChartResult]
	explanation_text: str
    
class ExplainModelTaskResponse(BaseModel):
	task_id: str
	status: str
	results: Optional[ExplainModelResult] = None

# Explain Chart Schema
class ExplainChartRequest(BaseModel):
	coin_symbol: str
	timeframe: int
	inference_time: datetime
	start: datetime
	end: datetime

class ExplainChartResponse(BaseModel):
	task_id: str

class SimilarChartResult(BaseModel):
	timestamp: datetime
	distance: float

class ExplainChartResult(BaseModel):
	similar_charts: List[SimilarChartResult]
	feature_values: Dict[str, float]
	explanation_text: str

class ExplainChartTaskResponse(BaseModel):
	task_id: str
	status: str
	results: Optional[ExplainChartResult] = None
