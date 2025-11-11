import random
import pandas as pd
import json

from app.strategies.strategy import Strategy

class RandomStrategy(Strategy):

    strategy_type = 'rule_based'
    inference_window = 1
    hyperparam_schema = {
        'buy_prob': {
            'default': 0.3,
            'type': 'float',
        },
        'sell_prob': {
            'default': 0.3,
            'type': 'float',
        }
    }

    def __init__(self):
        super().__init__()
        self.hyperparams = {}

    def action(self, inference_df: pd.DataFrame, cash_balance: float, coin_balance: float) -> tuple[int, float]:
        buy_prob = self.hyperparams.get('buy_prob', 0.3)
        sell_prob = self.hyperparams.get('sell_prob', 0.3)

        rand_value = random.random()
        if rand_value < buy_prob:
            action = 1  # Buy
        elif rand_value < buy_prob + sell_prob:
            action = -1  # Sell
        else:
            action = 0  # Hold

        current_price = inference_df.iloc[-1]['close']

        if action == -1:
            amount = coin_balance
        elif action == 1:
            amount = (cash_balance / current_price) * 0.9
        else:
            amount = 0.0
        return action, amount

    def train(self, train_df: pd.DataFrame, hyperparams: dict) -> None:
        self.hyperparams = hyperparams

    def load(self, path: str) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            self.hyperparams = json.load(f)

    def save(self, path: str) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.hyperparams, f)