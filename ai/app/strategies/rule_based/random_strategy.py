import random

from app.strategies.strategy import Strategy
from app.dataset import Dataset

class RandomStrategy(Strategy):

    strategy_type = 'rule_based'
    inference_window = 1
    hyperparam_schema = {
        'buy_prob': {
            'default': 0.3,
            'options': [0.1, 0.2, 0.3, 0.4, 0.5],

        },
        'sell_prob': {
            'default': 0.3,
            'options': [0.1, 0.2, 0.3, 0.4, 0.5],
        }
    }

    def __init__(self):
        super().__init__()
        self.hyperparams = {}

    def action(self, inference_dataset: Dataset, cash_balance: float, coin_balance: float) -> tuple[int, float]:
        buy_prob = self.hyperparams.get('buy_prob', 0.3)
        sell_prob = self.hyperparams.get('sell_prob', 0.3)

        rand_value = random.random()
        if rand_value < buy_prob:
            action = 1  # Buy
        elif rand_value < buy_prob + sell_prob:
            action = -1  # Sell
        else:
            action = 0  # Hold

        current_price = inference_dataset.data.iloc[-1]['Close']

        if action == -1:
            amount = coin_balance
        elif action == 1:
            amount = (cash_balance / current_price) * 0.9
        else:
            amount = 0.0
        return action, amount

    def train(self, train_dataset: Dataset, hyperparams: dict) -> None:
        self.hyperparams = hyperparams

    def load(self, path: str) -> None:
        pass  # No model

    def save(self, path: str) -> None:
        pass  # No model