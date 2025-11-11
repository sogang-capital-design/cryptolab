import pandas as pd

from app.celery_app import celery_app
from app.utils.model_load_utils import get_strategy_class, get_param_path
from app.utils.data_utils import get_ohlcv_df

@celery_app.task(bind=True)
def train_task(self, model_name: str, param_name: str, coin_symbol: str, timeframe: int, start: str, end: str, hyperparams: dict) -> None:
    strategy_class = get_strategy_class(model_name)
    cur_strategy = strategy_class()
    data_df = get_ohlcv_df(coin_symbol, timeframe)
    start, end = pd.to_datetime(start), pd.to_datetime(end)
    train_df = data_df.loc[start:end]

    cur_strategy.train(train_df, hyperparams)
    save_path = get_param_path(model_name, param_name)
    cur_strategy.save(save_path)
    return None