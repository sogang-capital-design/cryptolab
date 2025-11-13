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

def get_all_data_info() -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    data_path = _get_ohlcv_path()
    data_info = []
    for file_name in os.listdir(data_path):
        _, coin_symbol, start_time, end_time, _ = file_name.split('_')
        coin_symbol = coin_symbol.replace('KRW-', '').upper()
        start_timestamp = pd.to_datetime(start_time)
        end_timestamp = pd.to_datetime(end_time)
        data_info.append((coin_symbol, start_timestamp, end_timestamp))
    return data_info

def get_ohlcv_df(coin_symbol: str, timeframe: int) -> pd.DataFrame:
    coin_symbol = 'KRW-' + coin_symbol.upper()
    data_path = _get_ohlcv_path()
    for file_name in os.listdir(data_path):
        _, cur_coin_symbol, start_time, end_time, timeframe_with_csv = file_name.split('_')
        if coin_symbol == cur_coin_symbol:
            data_timeframe = int(timeframe_with_csv.replace('m.csv', ''))
            if timeframe % data_timeframe != 0:
                raise ValueError(f"Requested timeframe {timeframe} is not a multiple of data timeframe {data_timeframe}.")
            break
    else:
        raise FileNotFoundError("No matching data file found.")

    data_df = pd.read_csv(
        os.path.join(data_path, file_name),
        parse_dates=['datetime']
    )
    data_df = data_df.set_index("datetime").sort_index()

    def resample_to_minutes(df: pd.DataFrame, min: int) -> pd.DataFrame:
        df_resampled = pd.DataFrame()
        df_resampled['open']  = df['open'].resample(f'{min}min').first()
        df_resampled['high']  = df['high'].resample(f'{min}min').max()
        df_resampled['low']   = df['low'].resample(f'{min}min').min()
        df_resampled['close'] = df['close'].resample(f'{min}min').last()
        df_resampled['volume'] = df['volume'].resample(f'{min}min').sum()
        return df_resampled
    data_df = resample_to_minutes(data_df, timeframe).copy()
    return data_df
