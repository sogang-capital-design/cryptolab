from fastapi import APIRouter, HTTPException

from app.schemas.decide import DecisionRequest, DecisionResponse
from app.utils.model_load_utils import get_strategy_class, get_params_path
from app.utils.data_utils import get_total_dataset, get_n_last_rows

router = APIRouter()

@router.post("/", response_model=DecisionResponse)
async def decide(req: DecisionRequest) -> DecisionResponse:
    model_name, hyperparams = req.model_name, req.hyperparams
    coin_balance, cash_balance = req.coin_balance, req.cash_balance

    total_dataset = get_total_dataset()
    strategy_class = get_strategy_class(model_name)
    strategy_type = strategy_class.strategy_type
    inference_window = strategy_class.inference_window
    strategy_instance = strategy_class()

    if strategy_type != 'rule_based':
        params_path = get_params_path(model_name, strategy_type, hyperparams, create_path=False)
        strategy_instance.load(params_path)
    
    inference_dataset = get_n_last_rows(total_dataset, inference_window)

    action, amount = strategy_instance.action(
        inference_dataset=inference_dataset,
        cash_balance=cash_balance,
        coin_balance=coin_balance
    )
    return DecisionResponse(action=action, amount=amount)