import json
import ta
import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from tqdm import tqdm

from app.strategies.strategy import Strategy

class LightGBMStrategy(Strategy):

    strategy_type = 'tree_based'
    inference_window = 100
    hyperparam_schema = {
        "buy_threshold": {
            "default": 0.05,
            "type": "float",
        },
        "sell_threshold": {
            "default": -0.05,
            "type": "float",
        },
        "learning_rate": {
            "default": 0.05,
            "type": "float",
        },
        "num_leaves": {
            "default": 15,
            "type": "int",
        },
        "feature_fraction": {
            "default": 0.9,
            "type": "float",
        },
        "min_data_in_leaf": {
            "default": 20,
            "type": "int",
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
        features_df.drop(columns=["open", "high", "low", "close", "volume"], inplace=True)
        model_input = features_df.iloc[-1].values.reshape(1, -1)
        model_output = float(self.model.predict(model_input)[0])
        model_output = (np.exp(model_output) * 100) - 100

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
    
    def explain(self, train_df: pd.DataFrame, inference_df: pd.DataFrame) -> dict[str]:
        train_df = self._feature_engineering(train_df).dropna()
        train_df.drop(columns=["open", "high", "low", "close", "volume"], inplace=True)
        features_df = self._feature_engineering(inference_df).dropna()
        features_df.drop(columns=["open", "high", "low", "close", "volume"], inplace=True)
        model_input = features_df.iloc[-1:].values
        explainer = shap.TreeExplainer(
            self.model,
            data=train_df,
            feature_perturbation="interventional",
            model_output="raw"
        )
        prediction = self.model.predict(model_input)[0]
        prediction = (np.exp(prediction) * 100) - 100
        shap_results = explainer(model_input)
        features = shap_results.feature_names
        shap_value_dict = dict(zip(features, shap_results.values[0]))
        shap_value_dict = {k: float(v) for k, v in shap_value_dict.items()}
        feature_value_dict = dict(zip(features, shap_results.data[0]))
        feature_value_dict = {k: float(v) for k, v in feature_value_dict.items()}

        sorted_items = sorted(
            shap_value_dict.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        TOPK = 10

        topk_features = []
        price_selected = False

        for feat, val in sorted_items:
            # price_pct_change_* 는 하나만 선택
            if feat.startswith("price_pct_change"):
                if price_selected:
                    continue
                price_selected = True
            topk_features.append(feat)
            if len(topk_features) >= TOPK:
                break

        shap_value_dict = {k: shap_value_dict[k] for k in topk_features}
        feature_value_dict = {k: feature_value_dict[k] for k in topk_features}

        explanation = {
            "prediction": prediction,
            "shap_values": shap_value_dict,
            "feature_values": feature_value_dict,
        }
        return explanation
    
    def get_reference_train_data(self, train_df: pd.DataFrame, inference_df: pd.DataFrame, top_k: int = 5) -> dict:
        if self.model is None:
            raise RuntimeError("Model is not trained or loaded.")

        train_fe = self._feature_engineering(train_df).dropna()
        infer_fe = self._feature_engineering(inference_df).dropna()
        drop_cols = ["open", "high", "low", "close", "volume"]
        train_fe = train_fe.drop(columns=drop_cols, errors="ignore")
        infer_fe = infer_fe.drop(columns=drop_cols, errors="ignore")

        # 마지막 시점을 기준으로
        ref_ts = infer_fe.index[-1]
        ref_row = infer_fe.iloc[[-1]]

        train_leaf = np.array(self.model.predict(train_fe, pred_leaf=True))
        ref_leaf = np.array(self.model.predict(ref_row, pred_leaf=True))

        train_leaf = train_leaf.reshape(train_fe.shape[0], -1)
        ref_leaf = ref_leaf.reshape(-1)

        n_trees = train_leaf.shape[1]
        shared_ratio = (train_leaf == ref_leaf).sum(axis=1) / n_trees

        top_idx = np.argsort(-shared_ratio)[:top_k]
        similar_samples = [
            {"timestamp": str(train_fe.index[i]), "similarity": float(shared_ratio[i])}
            for i in top_idx
        ]
        return similar_samples

    def train(self, train_df: pd.DataFrame, hyperparams: dict) -> None:
        self.hyperparams = hyperparams

        lgb_hyperparams = {
            'objective': 'regression_l1',
            'metric': 'l1',
            'boosting_type': 'gbdt',
            'learning_rate': self._get_hyperparams('learning_rate'),
            'num_leaves': self._get_hyperparams('num_leaves'),
            'feature_fraction': self._get_hyperparams('feature_fraction'),
            'min_data_in_leaf': self._get_hyperparams('min_data_in_leaf'),
            "n_jobs": -1,
        }

        data_df = self._feature_engineering(train_df).dropna()
        X = data_df.copy()
        X.drop(columns=["open", "high", "low", "close", "volume"], inplace=True)

        # 로그 수익률 target
        y = np.log(data_df["close"].shift(-1) / data_df["close"])

        X_valid_idx = X.isna().sum(axis=1) == 0
        y_valid_idx = y.notna()
        valid_idx = X_valid_idx & y_valid_idx
        X = X[valid_idx]
        y = y[valid_idx]

        def balance_indices(y, random_state=42):
            rng = np.random.default_rng(random_state)
            pos_idx = np.where(y > 0)[0]
            neg_idx = np.where(y <= 0)[0]
            
            n = min(len(pos_idx), len(neg_idx))
            pos_sample = rng.choice(pos_idx, n, replace=False)
            neg_sample = rng.choice(neg_idx, n, replace=False)
            
            sel_idx = np.sort(np.concatenate([pos_sample, neg_sample]))
            return sel_idx

        sel_idx = balance_indices(y)
        X = X.iloc[sel_idx]
        y = y.iloc[sel_idx]

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
        trade_value = data_df["close"] * data_df["volume"]
        data_df["trade_value_z_score"] = (trade_value - trade_value.mean()) / trade_value.std()

        # 퍼센트 차이
        time_diffs = [1, 2, 3, 6, 12, 24, 48]
        for time_diff in time_diffs:
            data_df[f"price_pct_change_{time_diff}h"] = data_df["close"].pct_change(time_diff, fill_method=None)
            data_df[f"trade_value_pct_change_{time_diff}h"] = trade_value.pct_change(time_diff, fill_method=None)

        # 표준편차
        time_windows = [4, 12, 24]
        for time_window in time_windows:
            data_df[f"price_std_{time_window}"] = data_df["close"].rolling(time_window).std()

        # 볼린저 밴드
        hband = ta.volatility.BollingerBands(data_df["close"]).bollinger_hband()
        lband = ta.volatility.BollingerBands(data_df["close"]).bollinger_lband()
        data_df['rel_dist_to_bb_upper'] = (hband - data_df["close"]) / data_df["close"]
        data_df['rel_dist_to_bb_lower'] = (data_df["close"] - lband) / data_df["close"]

        # RSI
        data_df['rsi'] = ta.momentum.RSIIndicator(data_df["close"]).rsi()
        time_diffs = [2, 6, 24]
        for time_diff in time_diffs:
            data_df[f'rsi_pct_change_{time_diff}'] = data_df['rsi'].pct_change(time_diff, fill_method=None)

        # ADX
        data_df['adx'] = ta.trend.ADXIndicator(data_df["high"], data_df["low"], data_df["close"]).adx()

        # MACD
        macd = ta.trend.MACD(data_df["close"]).macd()
        macd_signal = ta.trend.MACD(data_df["close"]).macd_signal()
        time_diffs = [2, 6, 24]
        for time_diff in time_diffs:
            data_df[f'macd_pct_change_{time_diff}'] = macd.pct_change(time_diff, fill_method=None)
        data_df['rel_dist_to_signal'] = (macd - macd_signal) / macd

        # 최근 봉 관련 지표
        for shift_interval in range(5):
            close = data_df["close"].shift(shift_interval)
            open = data_df["open"].shift(shift_interval)
            high = data_df["high"].shift(shift_interval)
            low = data_df["low"].shift(shift_interval)

            body = abs(close - open)
            rng = (high - low).replace(0, np.nan)
            upper_wick = high - np.maximum(open, close)
            lower_wick = np.minimum(open, close) - low
            data_df[f"body_frac_{shift_interval}"] = body / rng
            data_df[f"upper_wick_frac_{shift_interval}"] = upper_wick / rng
            data_df[f"lower_wick_frac_{shift_interval}"] = lower_wick / rng
            data_df[f'cur_pct_change_{shift_interval}'] = (close - open) / open

        # 시간 feature
        data_df["hour"] = data_df.index.hour
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

        