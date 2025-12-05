import json
import ta
import lightgbm as lgb
import numpy as np
import pandas as pd
import shap
from tqdm import tqdm

from app.strategies.strategy import Strategy

import warnings
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

class LightGBMStrategy(Strategy):

    strategy_type = 'tree_based'
    inference_window = 100
    hyperparam_schema = {
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
        raise NotImplementedError("LightGBMStrategy does not support action method. Use explain() method for model explanations.")
    
    def explain(self, train_df: pd.DataFrame, inference_df: pd.DataFrame) -> dict[str]:
        train_df, _ = self._get_X_and_y(train_df)
        features_df, _ = self._get_X_and_y(inference_df)
        
        model_input = features_df.iloc[-1].values.reshape(1, -1)
        explainer = shap.TreeExplainer(
            self.model,
            data=train_df,
            feature_perturbation="interventional",
            model_output="raw"
        )
        prediction = self.model.predict(model_input)[0]
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
            if not np.isfinite(feature_value_dict[feat]):
                continue
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

        train_fe, _ = self._get_X_and_y(train_df)
        infer_fe, _ = self._get_X_and_y(inference_df)

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
        raise NotImplementedError("LightGBMStrategy does not support train method. Use load() to load a pre-trained model.")

    def _get_X_and_y(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        data_df = df.copy()
        data_df = data_df.drop(columns=['inst_inflow', 'inst_outflow'])
        all_cols = list(data_df.columns).copy()
        for col_name in all_cols:
            if 'volume' in col_name:
                usd_volume_name = col_name.replace('volume', 'usd_volume')
                data_df[usd_volume_name] = data_df[col_name] * data_df["price"]
                data_df = data_df.drop(columns=[col_name])

        all_cols = list(data_df.columns).copy()

        body = (data_df["close"] - data_df["open"]).abs()
        upper_wick = data_df["high"] - data_df[["close","open"]].max(axis=1)
        lower_wick = data_df[["close","open"]].min(axis=1) - data_df["low"]

        data_df["body_pct"] = body / (data_df["high"] - data_df["low"] + 1e-8)
        data_df["upper_wick_pct"] = upper_wick / (data_df["high"] - data_df["low"] + 1e-8)
        data_df["lower_wick_pct"] = lower_wick / (data_df["high"] - data_df["low"] + 1e-8)

        # 퍼센트 차이
        time_diffs = [1, 3, 6, 12, 24]
        for time_diff in time_diffs:
            for col in all_cols:
                if col not in ['open', 'high', 'low', 'close']:
                    data_df[f"{col}_pct_change_{time_diff}h"] = data_df[col].pct_change(time_diff)

        # 볼린저 밴드
        hband = ta.volatility.BollingerBands(data_df["price"]).bollinger_hband()
        lband = ta.volatility.BollingerBands(data_df["price"]).bollinger_lband()
        data_df['rel_dist_to_bb_upper'] = (hband - data_df["price"]) / data_df["price"]
        data_df['rel_dist_to_bb_lower'] = (data_df["price"] - lband) / data_df["price"]

        # EMA
        ema_20 = ta.trend.EMAIndicator(data_df["price"], window=20).ema_indicator()
        ema_60 = ta.trend.EMAIndicator(data_df["price"], window=60).ema_indicator()
        data_df['rel_dist_to_ema_20'] = (ema_20 - data_df["price"]) / data_df["price"]
        data_df['rel_dist_to_ema_60'] = (ema_60 - data_df["price"]) / data_df["price"]

        # RSI
        data_df['rsi'] = ta.momentum.RSIIndicator(data_df["price"]).rsi()
        for time_diff in time_diffs:
            data_df[f'rsi_pct_change_{time_diff}'] = data_df['rsi'].pct_change(time_diff)

        # MACD
        data_df["macd"] = ta.trend.MACD(close=data_df["price"]).macd()
        for time_diff in time_diffs:
            data_df[f'macd_pct_change_{time_diff}'] = data_df['macd'].pct_change(time_diff)

        # ATR
        atr = ta.volatility.AverageTrueRange(
            high=data_df["high"],
            low=data_df["low"],
            close=data_df["close"]
        )
        data_df["atr"] = atr.average_true_range()
        for time_diff in time_diffs:
            data_df[f'atr_pct_change_{time_diff}'] = data_df['atr'].pct_change(time_diff)

        data_df = data_df.drop(columns=['open', 'high', 'low', 'close'])
        data_df = data_df.copy()

        X = data_df.copy()
        X = X.drop(columns=['price'])

        # 로그 수익률 target (사용하지 않지만 호환성을 위해 유지)
        y = np.log(data_df['price'].shift(-1) / data_df['price'])

        return X, y
    
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

        
