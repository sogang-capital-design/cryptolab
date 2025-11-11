from fastapi import APIRouter, HTTPException

from app.schemas.models_schema import ModelInfoRequest, ModelInfoResponse, ModelListResponse
from app.utils.model_load_utils import get_strategy_class, _discover_strategies, STRATEGY_REGISTRY

router = APIRouter()

@router.get("/list", response_model=ModelListResponse)
def list_models() -> ModelListResponse:
    if not STRATEGY_REGISTRY:
        _discover_strategies()
    names = list(STRATEGY_REGISTRY.keys())
    return ModelListResponse(all_model_names=names)


@router.post("/info", response_model=ModelInfoResponse)
def get_model_info(req: ModelInfoRequest) -> ModelInfoResponse:
    try:
        strategy_cls = get_strategy_class(req.model_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"model '{req.model_name}' not found")

    strategy = strategy_cls()
    model_type = getattr(strategy, "strategy_type", None) or getattr(strategy, "model_type", "unknown")

    if hasattr(strategy_cls, "hyperparam_schema"):
        hyperparam_schema = strategy_cls.hyperparam_schema
    else:
        hyperparam_schema = {}

    return ModelInfoResponse(
        model_name=req.model_name,
        model_type=model_type,
        hyperparam_schema=hyperparam_schema,
    )
