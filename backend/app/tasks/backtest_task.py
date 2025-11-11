import pandas as pd
import backtrader as bt

from app.celery_app import celery_app
from app.utils.model_load_utils import get_strategy_class, get_param_path
from app.utils.data_utils import get_ohlcv_df
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
        inference_df = self.data_df.iloc[start_idx:end_idx]

        cash_balance = self.broker.get_cash()
        coin_balance = self.getposition(self.datas[0]).size

        action, amount = self.strategy_instance.action(
            inference_df=inference_df,
            cash_balance=cash_balance,
            coin_balance=coin_balance
        )
        if action == 1:
            self.buy(size=amount)
        elif action == -1:
            self.sell(size=amount)


@celery_app.task(bind=True)
def backtest_task(self, model_name: str, param_name: str, coin_symbol: str, timeframe: int, start: str, end: str) -> dict:
    start, end = pd.to_datetime(start), pd.to_datetime(end)
    strategy_class = get_strategy_class(model_name)
    cur_strategy = strategy_class()
    load_path = get_param_path(model_name, param_name)
    cur_strategy.load(load_path)

    data_df = get_ohlcv_df(coin_symbol, timeframe)
    data_df = data_df.loc[start:end]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(BacktestStrategy, strategy_instance=cur_strategy, data_df=data_df)
    cerebro.adddata(bt.feeds.PandasData(dataname=data_df))

    cerebro.broker.setcash(1000000.0)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    results = cerebro.run()
    strategy = results[0]
    trade_analyzer = strategy.analyzers.ta.get_analysis()
    returns_analyzer = strategy.analyzers.returns.get_analysis()

    win_rate = trade_analyzer.won.total / trade_analyzer.total.total if trade_analyzer.total.total > 0 else 0.0
    return_rate = returns_analyzer.get('rtot', 0.0)
    trade_count = trade_analyzer.total.total

    return {"win_rate": win_rate, "total_return": return_rate, "trade_count": trade_count}