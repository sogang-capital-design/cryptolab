from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

# Shared Schema
class FeatureValue(BaseModel):
	value: float
	display_name: Optional[str] = None
	interpretation: Optional[str] = None

# Explain Model Schema
class ExplainModelRequest(BaseModel):
	model_name: str
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
	shap_values: Dict[str, FeatureValue]
	feature_values: Dict[str, FeatureValue]
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

class ExplainChartResponse(BaseModel):
	task_id: str

class ExplainChartResult(BaseModel):
	feature_values: Dict[str, FeatureValue]
	explanation_text: str

class ExplainChartTaskResponse(BaseModel):
	task_id: str
	status: str
	results: Optional[ExplainChartResult] = None

# Explain Similar Chart Schema

class ExplainSimilarChartRequest(BaseModel):
	coin_symbol: str
	timeframe: int
	inference_time: datetime
	search_start: datetime
	search_end: datetime

class ExplainSimilarChartResponse(BaseModel):
	task_id: str

class SimilarChart(BaseModel):
	timestamp: datetime
	distance: float

class SimilarChartStats(BaseModel):
	price_up_count: int
	price_down_count: int
	feature_stats: Dict[str, 'DifferenceStats']
	
class DifferenceStats(BaseModel):
	up_value: float
	down_value: float
	diff: float
	pct_diff: float
	display_name: Optional[str] = None
	interpretation: Optional[str] = None

class ExplainSimilarChartResult(BaseModel):
	top_similar_charts: List[SimilarChart]
	similar_chart_stats: SimilarChartStats
	explanation_text: str

class ExplainSimilarChartTaskResponse(BaseModel):
	task_id: str
	status: str
	results: Optional[ExplainSimilarChartResult] = None