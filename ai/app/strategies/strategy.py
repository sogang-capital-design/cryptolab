from abc import ABC, abstractmethod
import pandas as pd

from app.dataset import Dataset

class Strategy(ABC):

    strategy_type: str
    inference_window: int
    hyperparam_schema: dict

    @abstractmethod
    def action(self, inference_dataset: Dataset, cash_balance: float, coin_balance: float) -> tuple[int, float]:
        pass

    @abstractmethod
    def train(self, train_dataset: Dataset, hyperparams: dict) -> None:
        pass

    @abstractmethod
    def load(self, path: str) -> None:
        pass

    @abstractmethod
    def save(self, path: str) -> None:
        pass