import pandas as pd

from app.schemas.explain_schema import ExplainRequest, ExplainResponse
from app.utils.model_load_utils import get_strategy_class, get_param_path
from app.utils.data_utils import get_ohlcv_df
from app.services.explain_service import get_explanation_text

if __name__ == "__main__":
    coin_symbol = "BTC"
    timeframe = 5
    model_name = "LightGBM"
    param_name = "v0"
    train_start = "2024-01-01 00:00:00"
    train_end = "2024-12-31 23:55:00"
    inference_time = "2024-02-01 12:00:00"

    total_df = get_ohlcv_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    strategy_class = get_strategy_class(model_name)
    inference_window = strategy_class.inference_window
    strategy_instance = strategy_class()

    params_path = get_param_path(model_name, param_name)
    strategy_instance.load(params_path)

    train_start_timestamp = pd.Timestamp(train_start).tz_localize(None)
    train_end_timestamp = pd.Timestamp(train_end).tz_localize(None)
    train_df = total_df.loc[train_start_timestamp:train_end_timestamp]

    inference_timestamp = pd.Timestamp(inference_time).tz_localize(None)
    inference_iloc = total_df.index.get_loc(inference_timestamp)
    inference_df = total_df.iloc[inference_iloc - inference_window:inference_iloc]

    print('Creating SHAP values...')
    explanation = strategy_instance.explain(
        train_df=train_df,
        inference_df=inference_df
    )
    print(explanation)
    print('Creating LLM explanation...')
    explanation_text = get_explanation_text(explanation)
    print(explanation_text)