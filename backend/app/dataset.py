import numpy as np
import pandas as pd

class Dataset:

    def __init__(self, data: pd.DataFrame) -> None:
        self._check_integrity(data)
        self._data = data.copy(deep=True)
        for col in self._data.columns:
            self._data[col].values.flags.writeable = False

    @property
    def data(self):
        return self._data

    def _check_integrity(self, df: pd.DataFrame) -> None:
        # 1. 인덱스 타입 확인
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("인덱스가 DatetimeIndex 형식이 아닙니다.")

        # 2. 중복된 인덱스 검사
        if df.index.duplicated().any():
            raise ValueError(f"중복된 timestamp가 존재합니다: {df.index[df.index.duplicated()].unique()}")

        # 3. NaN 값 검사
        if df.isnull().values.any():
            nan_cols = df.columns[df.isnull().any()].tolist()
            raise ValueError(f"NaN 값이 존재합니다 (컬럼: {nan_cols})")

        # 4. 음수 값 검사
        numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
        negative_mask = (df[numeric_cols] < 0).any(axis=1)
        if negative_mask.any():
            raise ValueError(f"음수 값이 존재합니다. 예시 행:\n{df[negative_mask].head()}")

        # 5. OHLC 논리적 관계 검사
        invalid_high_low = df["High"] < df["Low"]
        invalid_open_range = (df["Open"] < df["Low"]) | (df["Open"] > df["High"])
        invalid_close_range = (df["Close"] < df["Low"]) | (df["Close"] > df["High"])

        if invalid_high_low.any() or invalid_open_range.any() or invalid_close_range.any():
            raise ValueError(
                "OHLC 값의 논리적 관계가 잘못된 행이 존재합니다. 예시:\n"
                f"{df[invalid_high_low | invalid_open_range | invalid_close_range].head()}"
            )

        # 6. 시간 정렬 검사
        if not df.index.is_monotonic_increasing:
            raise ValueError("timestamp가 오름차순으로 정렬되어 있지 않습니다.")
