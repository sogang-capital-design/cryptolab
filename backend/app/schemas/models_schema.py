from datetime import datetime
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

class ModelListResponse(BaseModel):
    all_param_names: Dict[str, List[str]]
	
class ModelInfoRequest(BaseModel):
    model_name: str

class ModelInfoResponse(BaseModel):
    model_name: str
    hyperparam_schema: Dict[str, Any]
