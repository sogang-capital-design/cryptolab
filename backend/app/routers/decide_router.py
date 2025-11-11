import pandas as pd
from fastapi import APIRouter, HTTPException

from app.schemas.decide_schema import DecisionRequest, DecisionResponse
from app.utils.model_load_utils import get_strategy_class, get_param_path
from app.utils.data_utils import get_ohlcv_df

router = APIRouter()

@router.post("/", response_model=DecisionResponse)
async def decide(req: DecisionRequest) -> DecisionResponse:
    coin_balance, cash_balance = req.coin_balance, req.cash_balance

    total_df = get_ohlcv_df(
        coin_symbol=req.coin_symbol,
        timeframe=req.timeframe
    )
    strategy_class = get_strategy_class(req.model_name)
    inference_window = strategy_class.inference_window
    strategy_instance = strategy_class()

    params_path = get_param_path(req.model_name, req.param_name)
    strategy_instance.load(params_path)
    inference_timestamp = pd.Timestamp(req.inference_time).tz_localize(None)
    inference_iloc = total_df.index.get_loc(inference_timestamp)
    inference_df = total_df.iloc[inference_iloc - inference_window:inference_iloc]

    action, amount = strategy_instance.action(
        inference_df=inference_df,
        cash_balance=cash_balance,
        coin_balance=coin_balance
    )
    return DecisionResponse(action=action, amount=amount)