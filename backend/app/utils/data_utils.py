import os
import pandas as pd

from app.strategies.strategy import Strategy

def _get_data_path() -> str:
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.abspath(os.path.join(current_dir, '..', '..', 'data'))
    return data_dir

def _get_ohlcv_path() -> str:
    data_path = _get_data_path()
    ohlcv_path = os.path.join(data_path, 'ohlcv')
    return ohlcv_path

def get_ohlcv_df(coin_symbol: str, timeframe: int) -> pd.DataFrame:
    coin_symbol = 'KRW-' + coin_symbol.upper()
    data_path = _get_ohlcv_path()
    for file_name in os.listdir(data_path):
        _, cur_coin_symbol, start_time, end_time, timeframe_with_csv = file_name.split('_')
        cur_timeframe = timeframe_with_csv.replace('m.csv', '')
        if coin_symbol == cur_coin_symbol and timeframe == int(cur_timeframe):
            break
    else:
        raise FileNotFoundError("No matching data file found.")

    data_df = pd.read_csv(
        os.path.join(data_path, file_name),
        parse_dates=['datetime']
    )
    data_df = data_df.set_index("datetime").sort_index()
    return data_df
