import pandas as pd

from app.celery_app import celery_app
from app.utils.model_load_utils import get_strategy_class, get_params_path
from app.utils.data_utils import get_total_dataset
from app.dataset import Dataset


@celery_app.task(bind=True)
def train_task(self, model_name: str, start: str, end: str, hyperparams: dict) -> None:
    strategy_class = get_strategy_class(model_name)
    cur_strategy = strategy_class()
    data_df = get_total_dataset()
    start, end = pd.to_datetime(start), pd.to_datetime(end)
    train_df = data_df.data.loc[start:end]
    dataset = Dataset(train_df)
    cur_strategy.train(dataset, hyperparams)

    save_path = get_params_path(
        model_name=model_name,
        model_type=cur_strategy.strategy_type,
        hyperparams=hyperparams,
        create_path=True
    )
    cur_strategy.save(save_path)
    return None