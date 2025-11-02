import os
import pandas as pd

from app.strategies.strategy import Strategy
from app.dataset import Dataset

def _get_data_path() -> str:
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.abspath(os.path.join(current_dir, '..', '..', 'data'))
    return data_dir

def get_total_dataset() -> Dataset:
    file_name = 'ohlcv_KRW-BTC_202101010000_202501010000_60m.csv'
    data_path = _get_data_path()
    data_df = pd.read_csv(
        os.path.join(data_path, file_name),
        parse_dates=['timestamp']
    )
    data_df = data_df.set_index("timestamp").sort_index()
    data_df = data_df[['opening_price', 'high_price', 'low_price', 'trade_price', 'candle_acc_trade_volume']].copy()
    data_df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return Dataset(data_df)

def split_dataset_by_ratio(dataset: Dataset, train_ratio: float) -> tuple[Dataset, Dataset]:
    total_length = len(dataset.data)
    split_index = int(total_length * train_ratio)

    train_data = dataset.data.iloc[:split_index]
    test_data = dataset.data.iloc[split_index:]

    return Dataset(train_data), Dataset(test_data)

def split_dataset_by_date(dataset: Dataset, split_date: pd.Timestamp) -> tuple[Dataset, Dataset]:
    train_data = dataset.data[dataset.data.index < split_date]
    test_data = dataset.data[dataset.data.index >= split_date]

    return Dataset(train_data), Dataset(test_data)

def get_n_last_rows(dataset: Dataset, n: int) -> Dataset:
    last_n_data = dataset.data.tail(n)
    return Dataset(last_n_data)