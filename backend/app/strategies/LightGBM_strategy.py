import json
import ta
import lightgbm as lgb
import pandas as pd
from tqdm import tqdm

from app.strategies.strategy import Strategy

class LightGBMStrategy(Strategy):

    strategy_type = 'tree_based'
    inference_window = 100
    hyperparam_schema = {
        "buy_threshold": {
            "default": 0.7,
            "type": "float",
        },
        "sell_threshold": {
            "default": 0.3,
            "type": "float",
        },
        "learning_rate": {
            "default": 0.05,
            "type": "float",
        },
        "num_leaves": {
            "default": 31,
            "type": "int",
        },
        "feature_fraction": {
            "default": 0.9,
            "type": "float",
        },
        "bagging_fraction": {
            "default": 0.9,
            "type": "float",
        },
        "num_boost_round": {
            "default": 100,
            "type": "int",
        },
    }

    def __init__(self):
        super().__init__()
        self.hyperparams = {}
        self.model = None

    def _get_hyperparams(self, name: str):
        default = LightGBMStrategy.hyperparam_schema[name]['default']
        return self.hyperparams.get(name, default)

    def action(self, inference_df: pd.DataFrame, cash_balance: float, coin_balance: float) -> tuple[int, float]:
        buy_threshold = self._get_hyperparams('buy_threshold')
        sell_threshold = self._get_hyperparams('sell_threshold')

        features_df = self._feature_engineering(inference_df).dropna()
        model_input = features_df.iloc[-1].values.reshape(1, -1)
        model_output = float(self.model.predict(model_input)[0])

        if model_output < sell_threshold:
            action = -1  # Sell
        elif model_output > buy_threshold:
            action = 1  # Buy
        else:
            action = 0

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

        lgb_hyperparams = {
            'objective': 'binary',
            'metric': 'binary_error',
            'boosting_type': 'gbdt',
            'learning_rate': self._get_hyperparams('learning_rate'),
            'num_leaves': self._get_hyperparams('num_leaves'),
            'feature_fraction': self._get_hyperparams('feature_fraction'),
            'bagging_fraction': self._get_hyperparams('bagging_fraction'),
            "n_jobs": -1,
        }

        data_df = self._feature_engineering(train_df).dropna()
        X = data_df
        y = (data_df["close"].pct_change().shift(-1) > 0).astype(int)

        X_valid_idx = X.isna().sum(axis=1) == 0
        y_valid_idx = y.notna()
        valid_idx = X_valid_idx & y_valid_idx
        X = X[valid_idx]
        y = y[valid_idx]

        def tqdm_bar_callback(total_rounds):
            pbar = tqdm(total=total_rounds, desc="LightGBM Training", leave=True)
            def _callback(env):
                pbar.update(1)
                if env.iteration + 1 == total_rounds:
                    pbar.close()
            return _callback

        lgb_dataset = lgb.Dataset(X, label=y)
        self.model = lgb.train(
            params=lgb_hyperparams,
            train_set=lgb_dataset,
            num_boost_round=self._get_hyperparams('num_boost_round'),
            callbacks=[tqdm_bar_callback(self._get_hyperparams('num_boost_round'))]
        )
        print(self.model.params)

    def _feature_engineering(self, df: pd.DataFrame) -> pd.DataFrame:
        data_df = df.copy()
        data_df["trade_value"] = data_df["close"] * data_df["volume"]

        # 1) 거래 기반 지표
        time_diffs = [1, 3, 6, 12, 24]
        for time_diff in time_diffs:
            data_df[f"price_change_{time_diff}h"] = data_df["close"].pct_change(time_diff)
            data_df[f"volume_change_{time_diff}h"] = data_df["volume"].pct_change(time_diff)
            data_df[f"trade_value_change_{time_diff}h"] = data_df["trade_value"].pct_change(time_diff)

        # 2) 기술적 지표
        time_diffs = [12, 24, 48]
        for time_diff in time_diffs:
            data_df[f"rsi_{time_diff}"] = ta.momentum.RSIIndicator(data_df["close"], window=time_diff).rsi()
            data_df[f"sma_{time_diff}"] = ta.trend.SMAIndicator(data_df["close"], window=time_diff).sma_indicator()
            data_df[f"ema_{time_diff}"] = ta.trend.EMAIndicator(data_df["close"], window=time_diff).ema_indicator()
        data_df["macd"] = ta.trend.MACD(data_df["close"]).macd()
        data_df["bollinger_hband"] = ta.volatility.BollingerBands(data_df["close"]).bollinger_hband()

        # 3) 시간 feature
        data_df["hour"] = data_df.index.hour
        data_df["dayofweek"] = data_df.index.dayofweek
        data_df["is_weekend"] = (data_df["dayofweek"] >= 5).astype(int)
        return data_df

    def load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
            self.model = lgb.Booster(model_str=payload["model_str"])
            self.hyperparams = payload["hyperparams"]

    def save(self, path: str) -> None:
        payload = {
            "model_str": self.model.model_to_string(),
            "hyperparams": self.hyperparams,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        