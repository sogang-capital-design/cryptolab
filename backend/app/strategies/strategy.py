from abc import ABC, abstractmethod
import pandas as pd

class Strategy(ABC):

    strategy_type: str
    inference_window: int
    hyperparam_schema: dict

    @abstractmethod
    def action(self, inference_df: pd.DataFrame, cash_balance: float, coin_balance: float) -> tuple[int, float]:
        pass

    @abstractmethod
    def train(self, train_dataset: pd.DataFrame, hyperparams: dict) -> None:
        pass

    @abstractmethod
    def load(self, path: str) -> None:
        pass

    @abstractmethod
    def save(self, path: str) -> None:
        pass