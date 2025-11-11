from fastapi import APIRouter, HTTPException

from app.schemas.models_schema import ModelInfoRequest, ModelInfoResponse, ModelListResponse
from app.utils.model_load_utils import get_strategy_class, get_all_param_names

router = APIRouter()

@router.get("/list", response_model=ModelListResponse)
def list_models() -> ModelListResponse:
    names = get_all_param_names()
    return ModelListResponse(all_param_names=names)


@router.post("/info", response_model=ModelInfoResponse)
def get_model_info(req: ModelInfoRequest) -> ModelInfoResponse:
    try:
        strategy_cls = get_strategy_class(req.model_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"model '{req.model_name}' not found")

    if hasattr(strategy_cls, "hyperparam_schema"):
        hyperparam_schema = strategy_cls.hyperparam_schema
    else:
        hyperparam_schema = {}

    return ModelInfoResponse(
        model_name=req.model_name,
        hyperparam_schema=hyperparam_schema,
    )
