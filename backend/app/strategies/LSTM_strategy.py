import json
import ta
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import shap

from app.strategies.strategy import Strategy


class WindowDataset(Dataset):
    def __init__(self, X, y, window: int):
        self.X = X
        self.y = y
        self.window = window

    def __len__(self):
        n = len(self.X) - self.window
        return n if n > 0 else 0

    def __getitem__(self, idx):
        x_seq = self.X[idx: idx + self.window]  
        y_val = self.y[idx + self.window]    
        return (
            torch.tensor(x_seq, dtype=torch.float32),
            torch.tensor(y_val, dtype=torch.float32),
        )


class LSTMModel(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, num_layers: int,
                 dropout: float = 0.1, bidirectional: bool = False):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=(dropout if num_layers > 1 else 0.0),
            bidirectional=bidirectional,
        )
        out_dim = hidden_size * (2 if bidirectional else 1)
        self.fc = nn.Sequential(
            nn.Linear(out_dim, out_dim // 2),
            nn.ReLU(),
            nn.Linear(out_dim // 2, 1),
        )

    def forward(self, x):
        out, _ = self.lstm(x)       
        last = out[:, -1, :] 
        y = self.fc(last) 
        return y   


class LSTMStrategy(Strategy):

    strategy_type = "lstm"
    inference_window = 120
    hyperparam_schema = {
        "buy_threshold": {
            "default": 0.002,
            "type": "float",
        },
        "sell_threshold": {
            "default": -0.002,
            "type": "float",
        },
        "window": {
            "default": 60,  
            "type": "int",
        },
        "hidden_size": {
            "default": 64,
            "type": "int",
        },
        "num_layers": {
            "default": 2,
            "type": "int",
        },
        "dropout": {
            "default": 0.1,
            "type": "float",
        },
        "bidirectional": {
            "default": 0, 
            "type": "int",
        },
        "learning_rate": {
            "default": 1e-3,
            "type": "float",
        },
        "batch_size": {
            "default": 32,
            "type": "int",
        },
        "num_epochs": {
            "default": 20,
            "type": "int",
        },
    }

    feature_cols = [
        "close",
        "ret",
        "ma5", "ma10", "ma20",
        "dev5", "dev10", "dev20",
        "bb_pos",
        "rsi14",
        "vol_dev20",
    ]
    
    def __init__(self):
        super().__init__()
        self.hyperparams = {}
        self.model = None

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.feat_mean = None
        self.feat_std = None
        self.close_mean = None
        self.close_std = None

        self.window = int(LSTMStrategy.hyperparam_schema["window"]["default"])
        self.inference_window = LSTMStrategy.inference_window

    def _get_hyperparams(self, name: str):
        default = LSTMStrategy.hyperparam_schema[name]["default"]
        return self.hyperparams.get(name, default)

    def action(self, inference_df: pd.DataFrame,
               cash_balance: float,
               coin_balance: float) -> tuple[int, float]:
        if (
            self.model is None or
            self.feat_mean is None or
            self.feat_std is None or
            self.close_mean is None or
            self.close_std is None
        ):
            return 0, 0.0

        fe_df = self._feature_engineering(inference_df).dropna()
        if len(fe_df) < self.window:
            return 0, 0.0

        X_all = fe_df[LSTMStrategy.feature_cols].astype("float32").values 
        X_last = X_all[-self.window:]                                    

        X_last_norm = (X_last - self.feat_mean) / self.feat_std

        x_tensor = torch.tensor(
            X_last_norm, dtype=torch.float32, device=self.device
        ).unsqueeze(0) 

        self.model.eval()
        with torch.no_grad():
            pred_norm = float(self.model(x_tensor).item())

        pred_price = pred_norm * self.close_std + self.close_mean

        current_price = float(fe_df["close"].iloc[-1])

        expected_ret = (pred_price / current_price) - 1.0

        buy_threshold = float(self._get_hyperparams("buy_threshold"))
        sell_threshold = float(self._get_hyperparams("sell_threshold"))

        if expected_ret < sell_threshold:
            action = -1  # Sell
        elif expected_ret > buy_threshold:
            action = 1   # Buy
        else:
            action = 0   # Hold

        if action == -1:
            amount = float(coin_balance)  # 전량 매도
        elif action == 1:
            if current_price <= 0:
                return 0, 0.0
            amount = (float(cash_balance) / current_price) * 0.9  # 90% 매수
        else:
            amount = 0.0

        print(
            f"[LSTM Pred] current={current_price:.2f}, pred={pred_price:.2f}, "
            f"exp_ret={expected_ret:.5f}, action={action}, amount={amount}"
        )
        return action, amount
    
    def explain(self, train_df: pd.DataFrame, inference_df: pd.DataFrame) -> dict[str]:
        if (
            self.model is None or
            self.feat_mean is None or
            self.feat_std is None or
            self.close_mean is None or
            self.close_std is None
        ):
            return {
                "prediction": None,
                "shap_values": {},
                "feature_values": {},
            }

        train_fe = self._feature_engineering(train_df).dropna().reset_index(drop=True)
        infer_fe = self._feature_engineering(inference_df).dropna(subset=LSTMStrategy.feature_cols).reset_index(drop=True)

        X_train = train_fe[LSTMStrategy.feature_cols].astype("float32").values 
        X_infer = infer_fe[LSTMStrategy.feature_cols].astype("float32").values  

        X_train_norm = (X_train - self.feat_mean) / self.feat_std
        X_infer_norm = (X_infer - self.feat_mean) / self.feat_std

        if len(X_train_norm) <= self.window or len(X_infer_norm) < self.window:
            return {
                "prediction": None,
                "shap_values": {},
                "feature_values": {},
            }

        seq_list = []
        for i in range(len(X_train_norm) - self.window):
            seq = X_train_norm[i : i + self.window]  
            seq_list.append(seq)

        bg_seqs = np.stack(seq_list, axis=0)          

        max_bg = 200
        if bg_seqs.shape[0] > max_bg:
            idx = np.linspace(0, bg_seqs.shape[0] - 1, max_bg).astype(int)
            bg_seqs = bg_seqs[idx]

        background_tensor = torch.tensor(
            bg_seqs, dtype=torch.float32, device=self.device
        )

        x_last_seq_norm = X_infer_norm[-self.window:] 
        x_tensor = torch.tensor(
            x_last_seq_norm, dtype=torch.float32, device=self.device
        ).unsqueeze(0)                          

        self.model.eval()
        with torch.no_grad():
            pred_norm = float(self.model(x_tensor).item()) 

        pred_price = pred_norm * self.close_std + self.close_mean

        current_price = float(infer_fe["close"].iloc[-1])
        expected_ret = (pred_price / current_price) - 1.0  

        prediction = float(expected_ret) 

        explainer = shap.DeepExplainer(self.model, background_tensor)

        shap_values = explainer.shap_values(x_tensor)
        if isinstance(shap_values, list):
            shap_values = shap_values[0]

        shap_values = shap_values[0]    

        shap_per_feature = shap_values.mean(axis=0)   

        features = LSTMStrategy.feature_cols
        last_feature_vals = X_infer[-1]                

        shap_value_dict = dict(zip(features, shap_per_feature))
        shap_value_dict = {k: float(v) for k, v in shap_value_dict.items()}

        feature_value_dict = dict(zip(features, last_feature_vals))
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
            "prediction": prediction,               # 기대 수익률 (float)
            "shap_values": shap_value_dict,         # TOPK feature → shap 값
            "feature_values": feature_value_dict,   # 그 feature들의 실제 값
        }
        return explanation
    
    def get_reference_train_data(self, train_df: pd.DataFrame, inference_df: pd.DataFrame, top_k: int = 5,) -> list[dict]:
        if self.model is None:
            return []

        train_fe = self._feature_engineering(train_df).dropna()
        infer_fe = self._feature_engineering(inference_df).dropna(subset=self.feature_cols)

        X_train = train_fe[self.feature_cols].astype("float32").values
        X_infer = infer_fe[self.feature_cols].astype("float32").values

        x_ref = X_infer[-1]

        eps = 1e-9
        rel_diff = np.abs(X_train - x_ref) / (np.abs(x_ref) + eps)

        mean_rel_diff = rel_diff.mean(axis=1)

        sims = 1.0 / (1.0 + mean_rel_diff)

        top_idx = np.argsort(-sims)[:top_k]

        similar_samples = [
            {
                "timestamp": str(train_fe.index[i]),
                "similarity": float(sims[i]),
            }
            for i in top_idx
        ]
        return similar_samples

    def train(self, train_df: pd.DataFrame, hyperparams: dict) -> None:
        self.hyperparams = hyperparams or {}

        self.window = int(self._get_hyperparams("window"))
        hidden_size = int(self._get_hyperparams("hidden_size"))
        num_layers = int(self._get_hyperparams("num_layers"))
        dropout = float(self._get_hyperparams("dropout"))
        bidirectional = bool(int(self._get_hyperparams("bidirectional")))
        lr = float(self._get_hyperparams("learning_rate"))
        batch_size = int(self._get_hyperparams("batch_size"))
        num_epochs = int(self._get_hyperparams("num_epochs"))

        fe_df = self._feature_engineering(train_df)
        fe_df = fe_df.dropna().reset_index(drop=True)

        X = fe_df[LSTMStrategy.feature_cols].astype("float32").values
        y_close = fe_df["close"].astype("float32").values

        self.feat_mean = X.mean(axis=0, keepdims=True)
        self.feat_std = X.std(axis=0, keepdims=True) + 1e-8
        X_norm = (X - self.feat_mean) / self.feat_std

        self.close_mean = float(y_close.mean())
        self.close_std = float(y_close.std() + 1e-8)
        y_norm = (y_close - self.close_mean) / self.close_std

        dataset = WindowDataset(X_norm, y_norm, window=self.window)
        if len(dataset) <= 0:
            raise ValueError(
                "Not enough data to create sequences. "
                "Check train_df length and window size."
            )

        loader = DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=True,
            drop_last=True,
        )

        input_size = X.shape[1]
        self.model = LSTMModel(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            bidirectional=bidirectional,
        ).to(self.device)

        criterion = torch.nn.SmoothL1Loss(beta=0.01)
        optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=lr,               
            weight_decay=1e-5,
        )
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode="min",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
        )

        self.model.train()
        for epoch in range(num_epochs):
            running_loss = 0.0
            n_samples = 0

            for xb, yb in loader:
                xb = xb.to(self.device)
                yb = yb.to(self.device)

                optimizer.zero_grad()
                preds = self.model(xb)
                loss = criterion(preds, yb)
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()

                running_loss += loss.item() * xb.size(0)
                n_samples += xb.size(0)

            epoch_loss = running_loss / max(1, n_samples)
            scheduler.step(epoch_loss)
            print(f"[LSTMStrategy] Epoch {epoch+1:02d}/{num_epochs} | Train Loss: {epoch_loss:.4f}")

    def _feature_engineering(self, df: pd.DataFrame) -> pd.DataFrame:
        data_df = df.copy()

        # log return
        data_df["ret"] = np.log(data_df["close"]).diff()

        # 이동평균 & 편차
        for w in [5, 10, 20]:
            data_df[f"ma{w}"] = data_df["close"].rolling(w).mean()
            data_df[f"dev{w}"] = (
                data_df["close"] - data_df[f"ma{w}"]
            ) / (data_df[f"ma{w}"] + 1e-9)

        # Bollinger 기반 포지션 (20, 2σ)
        w = 20
        data_df["bb_mid"] = data_df["close"].rolling(w).mean()
        data_df["bb_std"] = data_df["close"].rolling(w).std(ddof=0)
        data_df["bb_up"] = data_df["bb_mid"] + 2 * data_df["bb_std"]
        data_df["bb_dn"] = data_df["bb_mid"] - 2 * data_df["bb_std"]
        data_df["bb_pos"] = (data_df["close"] - data_df["bb_mid"]) / (
            data_df["bb_std"] + 1e-9
        )

        # RSI(14)
        window = 14
        delta = data_df["close"].diff()

        up = delta.clip(lower=0)                  # 음수는 0으로
        dn = (-delta).clip(lower=0)               # 양수는 0으로, 음수 뒤집기

        roll_up = up.rolling(window).mean()
        roll_dn = dn.rolling(window).mean()

        rs = roll_up / (roll_dn + 1e-9)
        data_df["rsi14"] = 100 - (100 / (1 + rs))

        # 거래량 변동성
        data_df["vol_ma20"] = data_df["volume"].rolling(20).mean()
        data_df["vol_dev20"] = (
            data_df["volume"] - data_df["vol_ma20"]
        ) / (data_df["vol_ma20"] + 1e-9)

        return data_df

    def load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        self.hyperparams = payload.get("hyperparams", {})

        self.window = payload.get(
            "window",
            LSTMStrategy.hyperparam_schema["window"]["default"],
        )
        self.inference_window = LSTMStrategy.inference_window

        hidden_size = int(self._get_hyperparams("hidden_size"))
        num_layers = int(self._get_hyperparams("num_layers"))
        dropout = float(self._get_hyperparams("dropout"))
        bidirectional = bool(int(self._get_hyperparams("bidirectional")))
        input_size = len(LSTMStrategy.feature_cols)

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = LSTMModel(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            bidirectional=bidirectional,
        ).to(self.device)

        state_dict_serializable = payload["state_dict"]
        state_dict = {k: torch.tensor(v) for k, v in state_dict_serializable.items()}
        self.model.load_state_dict(state_dict)

        feat_mean = payload.get("feat_mean", None)
        feat_std = payload.get("feat_std", None)

        self.feat_mean = np.array(feat_mean, dtype=np.float32) if feat_mean is not None else None
        self.feat_std = np.array(feat_std, dtype=np.float32) if feat_std is not None else None
        self.close_mean = payload.get("close_mean", None)
        self.close_std = payload.get("close_std", None)

    def save(self, path: str) -> None:
        if self.model is None:
            raise RuntimeError("Model is not trained, cannot save.")

        state_dict = self.model.state_dict()
        state_dict_serializable = {k: v.cpu().tolist() for k, v in state_dict.items()}

        feat_mean = self.feat_mean.tolist() if isinstance(self.feat_mean, np.ndarray) else None
        feat_std = self.feat_std.tolist() if isinstance(self.feat_std, np.ndarray) else None

        payload = {
            "hyperparams": self.hyperparams,
            "state_dict": state_dict_serializable,
            "feat_mean": feat_mean,
            "feat_std": feat_std,
            "close_mean": self.close_mean,
            "close_std": self.close_std,
            "window": self.window,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        
