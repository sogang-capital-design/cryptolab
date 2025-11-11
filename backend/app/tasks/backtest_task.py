import pandas as pd
import backtrader as bt

from app.celery_app import celery_app
from app.utils.model_load_utils import get_strategy_class, get_params_path
from app.utils.data_utils import get_total_dataset
from app.dataset import Dataset
from app.strategies.strategy import Strategy

class BacktestStrategy(bt.Strategy):
    def __init__(self, strategy_instance: Strategy, data_df: pd.DataFrame):
        self.strategy_instance = strategy_instance
        self.data_df = data_df
        self.inference_window = strategy_instance.inference_window

    def next(self):
        if len(self) < self.inference_window:
            return

        start_idx = len(self) - self.inference_window
        end_idx = len(self)
        inference_data = self.data_df.iloc[start_idx:end_idx]
        inference_dataset = Dataset(inference_data)

        cash_balance = self.broker.get_cash()
        coin_balance = self.getposition(self.datas[0]).size

        action, amount = self.strategy_instance.action(
            inference_dataset=inference_dataset,
            cash_balance=cash_balance,
            coin_balance=coin_balance
        )
        if action == 1:
            self.buy(size=amount)
        elif action == -1:
            self.sell(size=amount)


@celery_app.task(bind=True)
def backtest_task(self, model_name: str, start: str, end: str, hyperparams: dict) -> dict:
    start, end = pd.to_datetime(start), pd.to_datetime(end)
    strategy_class = get_strategy_class(model_name)
    cur_strategy = strategy_class()
    load_path = get_params_path(
        model_name=model_name,
        model_type=cur_strategy.strategy_type,
        hyperparams=hyperparams,
        create_path=False
    )
    cur_strategy.load(load_path)

    data_df = get_total_dataset()
    data_df = data_df.data.loc[start:end]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(BacktestStrategy, strategy_instance=cur_strategy, data_df=data_df)
    cerebro.adddata(bt.feeds.PandasData(dataname=data_df))

    cerebro.broker.setcash(1000000.0)
    cerebro.broker.setcommission(commission=0.0005)

    print(f"시작 자산: {cerebro.broker.getvalue():,.2f}")
    results = cerebro.run()
    print(f"최종 자산: {cerebro.broker.getvalue():,.2f}")
    return {"status": "success"}