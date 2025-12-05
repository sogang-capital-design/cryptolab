import json
import ta
import numpy as np
import pandas as pd
import math
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import shap

from app.strategies.strategy import Strategy

class WindowDataset(Dataset):
    def __init__(self, X_seq, y_ret_scaled):
        self.X = X_seq
        self.y_ret = y_ret_scaled

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x_seq = self.X[idx]      
        y_ret = self.y_ret[idx]     
        return (
            torch.tensor(x_seq, dtype=torch.float32),
            torch.tensor(y_ret, dtype=torch.float32),
        )

class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 5000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float32)
            * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        T = x.size(1)
        return x + self.pe[:, :T, :]
    
class TransformerModel(nn.Module):
    def __init__(
        self,
        input_size: int,
        d_model: int,
        num_layers: int,
        nhead: int = 4,
        dim_feedforward: int = 128,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.input_proj = nn.Linear(input_size, d_model)
        self.pos_enc = PositionalEncoding(d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.fc_out = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, T, F)
        h = self.input_proj(x)
        h = self.pos_enc(h)
        z = self.encoder(h)
        last = z[:, -1, :]         # (B, d_model)
        out = self.fc_out(last)    # (B, 1)
        return out.squeeze(-1)     # (B,)

class TransformerStrategy(Strategy):

    strategy_type = 'transformer'
    inference_window = 100
    hyperparam_schema = {
        "buy_threshold": {
            "default": 0.001, 
            "type": "float"
        },
        "sell_threshold": {
            "default": 0.001, 
            "type": "float"
        },
        "seq_len": {
            "default": 64,
            "type": "int"
        },
        "d_model": {
            "default": 96,
            "type": "int"
        },
        "nhead": {
            "default": 4,
            "type": "int"
        },
        "num_layers": {
            "default": 3,
            "type": "int"
        },
        "ff": {
            "default": 192,
            "type": "int"
        },
        "dropout": {
            "default": 0.2,
            "type": "float"
        },
        "learning_rate": {
            "default": 7e-4,
            "type": "float"
        },
        "weight_decay": {
            "default": 3e-4,
            "type": "float"
        },
        "batch_size": {
            "default": 64,
            "type": "int"
        },
        "num_epochs": {
            "default": 20, 
            "type": "int"
        },
        "alpha_bce": {
            "default": 1.8, 
            "type": "float"
        },
        "beta_reg": {
            "default": 1.0, 
            "type": "float"
        },
    }

    feature_cols = [
        "g", "g_ma5", "g_ma20",
        "ret_std5", "ret_std20",
        "hl_spread", "oc_spread",
        "log_vol", "log_val",
        "rsi_state", "macd_cross", "bb_state", "bb_perc_b",
    ]

    def __init__(self):
        super().__init__()
        self.hyperparams = {}
        self.model = None

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.feat_mean = None
        self.feat_std = None

        self.seq_len = int(self.hyperparam_schema["seq_len"]["default"])
        self.inference_window = self.seq_len + 50

    def _get_hyperparams(self, name: str):
        default = TransformerStrategy.hyperparam_schema[name]['default']
        return self.hyperparams.get(name, default)

    def _make_sequences(self, X_norm: np.ndarray, y_ret_scaled: np.ndarray, seq_len: int):
        T = X_norm.shape[0]
        if T < seq_len:
            return (
                np.empty((0, seq_len, X_norm.shape[1]), dtype=np.float32),
                np.empty((0,), dtype=np.float32),
            )

        X_list, y_list = [], []
        for i in range(seq_len - 1, T):
            x_seq = X_norm[i - seq_len + 1: i + 1]    
            X_list.append(x_seq)
            y_list.append(float(y_ret_scaled[i]))    

        X_seq = np.stack(X_list, axis=0).astype(np.float32)
        y_seq = np.array(y_list, dtype=np.float32)
        return X_seq, y_seq

    def action(self, inference_df: pd.DataFrame, cash_balance: float, coin_balance: float) -> tuple[int, float]:
        if (
            self.model is None or
            self.feat_mean is None or
            self.feat_std is None
        ):
            return 0, 0.0

        fe_df = self._feature_engineering(inference_df).dropna()
        if len(fe_df) < self.seq_len:
            return 0, 0.0

        X_all = fe_df[self.feature_cols].astype("float32").values   # (T, F)
        X_last = X_all[-self.seq_len:]                              # (L, F)

        X_last_norm = (X_last - self.feat_mean) / self.feat_std     # (L, F)

        x_tensor = torch.tensor(
            X_last_norm, dtype=torch.float32, device=self.device
        ).unsqueeze(0)  # (1, L, F)

        self.model.eval()
        with torch.no_grad():
            pred_scaled = float(self.model(x_tensor).item())

        ret_std20_last = float(fe_df["ret_std20"].iloc[-1])
        if not math.isfinite(ret_std20_last) or abs(ret_std20_last) < 1e-12:
            return 0, 0.0

        g_hat = pred_scaled * ret_std20_last         
        expected_ret = math.exp(g_hat) - 1.0         

        current_price = float(fe_df["close"].iloc[-1])

        buy_threshold = float(self._get_hyperparams('buy_threshold'))
        sell_threshold = float(self._get_hyperparams('sell_threshold'))

        if expected_ret < sell_threshold:
            action = -1  # Sell
        elif expected_ret > buy_threshold:
            action = 1   # Buy
        else:
            action = 0   # Hold

        if action == -1:
            amount = float(coin_balance)  
        elif action == 1:
            if current_price <= 0:
                return 0, 0.0
            amount = (float(cash_balance) / current_price) * 0.9  
        else:
            amount = 0.0

        print(
            f"[Transformer Pred] current={current_price:.2f}, "
            f"exp_ret={expected_ret:.5f}, action={action}, amount={amount}"
        )
        return action, amount
    
    def explain(self, train_df: pd.DataFrame, inference_df: pd.DataFrame) -> dict[str]:
        if self.model is None or self.feat_mean is None or self.feat_std is None:
            return {
                "prediction": None,
                "shap_values": {},
                "feature_values": {},
                "message": "Model is not trained or normalization stats are missing.",
            }

        fe_df = self._feature_engineering(inference_df)
        # inference 시에는 마지막 행을 유지하기 위해 feature columns에 대해서만 dropna
        fe_df = fe_df.dropna(subset=self.feature_cols)
        if len(fe_df) < self.seq_len + 1:
            return {
                "prediction": None,
                "shap_values": {},
                "feature_values": {},
                "message": f"Not enough inference data for explanation (need >= {self.seq_len + 1} rows).",
            }

        X_all = fe_df[self.feature_cols].astype("float32").values 
        X_last = X_all[-self.seq_len:]                           

        X_last_norm = (X_last - self.feat_mean) / self.feat_std    

        ret_std20_last = float(fe_df["ret_std20"].iloc[-1])
        close_last = float(fe_df["close"].iloc[-1])
        if not math.isfinite(ret_std20_last) or abs(ret_std20_last) < 1e-12:
            return {
                "prediction": None,
                "shap_values": {},
                "feature_values": {},
                "message": "Invalid ret_std20 for explanation.",
            }

        x_leaf = torch.tensor(
            X_last_norm,
            dtype=torch.float32,
            device=self.device,
            requires_grad=True,
        ) 

        x_input = x_leaf.unsqueeze(0) 

        self.model.eval()
        with torch.enable_grad():
            pred_scaled = self.model(x_input)  
            pred_scalar = pred_scaled.squeeze()

        self.model.zero_grad(set_to_none=True)
        pred_scalar.backward()

        grads = x_leaf.grad.detach().cpu().numpy()
        X_last_norm_np = X_last_norm

        contrib = np.mean(grads * X_last_norm_np, axis=0) 

        pred_scaled_val = float(pred_scalar.item())
        g_hat = pred_scaled_val * ret_std20_last      
        expected_ret = math.exp(g_hat) - 1.0              

        shap_value_dict = {}
        feature_value_dict = {}
        last_feat_values = X_last[-1]   

        for j, col in enumerate(self.feature_cols):
            shap_value_dict[col] = float(contrib[j])
            feature_value_dict[col] = float(last_feat_values[j])

        explanation = {
            "prediction": expected_ret,
            "shap_values": shap_value_dict,
            "feature_values": feature_value_dict,
        }
        return explanation

    
    def get_reference_train_data(self, train_df: pd.DataFrame, inference_df: pd.DataFrame,top_k: int = 5,):
        if self.model is None or self.feat_mean is None or self.feat_std is None:
            return []

        train_fe = self._feature_engineering(train_df).dropna()
        infer_fe = self._feature_engineering(inference_df).dropna(subset=self.feature_cols)
        if len(train_fe) == 0 or len(infer_fe) == 0:
            return []

        try:
            X_train = train_fe[self.feature_cols].astype("float32").values  # (N_train, F)
            X_ref_all = infer_fe[self.feature_cols].astype("float32").values
        except KeyError:
            return []

        ref_vec = X_ref_all[-1]   
        if not np.all(np.isfinite(ref_vec)):
            return []

        eps = 1e-8
        denom = np.abs(ref_vec) + eps       
        abs_diff = np.abs(X_train - ref_vec)   
        rel_diff = abs_diff / denom           

        mean_rel_diff = np.mean(rel_diff, axis=1)         
        sims = 1.0 / (1.0 + mean_rel_diff)            

        if len(sims) == 0:
            return []
        top_idx = np.argsort(-sims)[:top_k]

        similar_samples = []
        for i in top_idx:
            ts = train_fe.index[i]
            similar_samples.append({
                "timestamp": str(ts),
                "similarity": float(sims[i]),
            })

        return similar_samples


    def train(self, train_df: pd.DataFrame, hyperparams: dict) -> None:
        self.hyperparams = hyperparams or {}

        # ---- 하이퍼파라 읽기 ----
        self.seq_len = int(self._get_hyperparams("seq_len"))
        self.inference_window = self.seq_len + 50

        d_model = int(self._get_hyperparams("d_model"))
        nhead = int(self._get_hyperparams("nhead"))
        num_layers = int(self._get_hyperparams("num_layers"))
        ff = int(self._get_hyperparams("ff"))
        dropout = float(self._get_hyperparams("dropout"))

        lr = float(self._get_hyperparams("learning_rate"))
        weight_decay = float(self._get_hyperparams("weight_decay"))
        batch_size = int(self._get_hyperparams("batch_size"))
        num_epochs = int(self._get_hyperparams("num_epochs"))

        # ---- 피처 엔지니어링 ----
        fe_df = self._feature_engineering(train_df).dropna().reset_index(drop=True)

        # X, y 만들기
        X = fe_df[self.feature_cols].astype("float32").values             # (T, F)
        y_ret_scaled = fe_df["y_ret_scaled"].astype("float32").values     # (T,)

        # ---- 정규화 ----
        self.feat_mean = X.mean(axis=0, keepdims=True).astype(np.float32)
        self.feat_std = X.std(axis=0, keepdims=True).astype(np.float32) + 1e-8
        X_norm = (X - self.feat_mean) / self.feat_std

        # ---- 시퀀스 데이터 만들기 ----
        X_seq, y_seq = self._make_sequences(X_norm, y_ret_scaled, self.seq_len)
        if len(X_seq) == 0:
            raise ValueError(
                f"Not enough data to create sequences. len(X)={len(X)}, seq_len={self.seq_len}"
            )

        dataset = WindowDataset(X_seq, y_seq)
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=False)

        # ---- 모델 생성 ----
        input_size = X_seq.shape[2]
        self.model = TransformerModel(
            input_size=input_size,
            d_model=d_model,
            num_layers=num_layers,
            nhead=nhead,
            dim_feedforward=ff,
            dropout=dropout,
        ).to(self.device)

        criterion = nn.SmoothL1Loss() 
        optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=lr,
            weight_decay=weight_decay,
        )

        # ---- 학습 루프 ----
        self.model.train()
        for epoch in range(1, num_epochs + 1):
            total_loss = 0.0
            n_samples = 0

            for xb, yb in loader:
                xb = xb.to(self.device)     # (B, L, F)
                yb = yb.to(self.device)     # (B,)

                optimizer.zero_grad()
                pred = self.model(xb)       # (B,)
                loss = criterion(pred, yb)
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()

                total_loss += loss.item() * xb.size(0)
                n_samples += xb.size(0)

            avg_loss = total_loss / max(1, n_samples)
            print(
                f"[TransformerStrategy] Epoch {epoch:02d}/{num_epochs} | "
                f"Train Loss: {avg_loss:.4f}"
            )


    def _feature_engineering(self, df: pd.DataFrame) -> pd.DataFrame:
        data_df = df.copy()

        if "value" not in data_df.columns:
            data_df["value"] = (
                pd.to_numeric(data_df["close"], errors="coerce")
                * pd.to_numeric(data_df["volume"], errors="coerce")
            )

        # ----- 기본 로그 수익률 및 변동성 -----
        data_df["log_close"] = np.log(data_df["close"].astype(float))
        data_df["g"] = data_df["log_close"].diff(1)
        data_df["ret_std5"] = data_df["g"].rolling(5).std()
        data_df["ret_std20"] = data_df["g"].rolling(20).std()

        # 다음 시점 로그수익률 및 타깃
        data_df["g_next"] = data_df["g"].shift(-1)
        data_df["dir_next"] = (data_df["g_next"] > 0).astype(int)              # 방향(0/1)
        data_df["y_ret_scaled"] = data_df["g_next"] / (data_df["ret_std20"] + 1e-12)

        # ----- 수익률 이동평균 등 -----
        data_df["g_ma5"] = data_df["g"].rolling(5).mean()
        data_df["g_ma20"] = data_df["g"].rolling(20).mean()

        # 고저/시가-종가 스프레드
        data_df["hl_spread"] = (data_df["high"] - data_df["low"]) / data_df["close"]
        data_df["oc_spread"] = (data_df["close"] - data_df["open"]) / (
            data_df["open"] + 1e-12
        )

        # 거래량/거래대금 로그
        data_df["log_vol"] = np.log(data_df["volume"].astype(float) + 1.0)
        data_df["log_val"] = np.log(data_df["value"].astype(float) + 1.0)

        close = data_df["close"].astype(float)

        # --- MACD ---
        ema_fast, ema_slow, ema_signal = 12, 26, 9
        ema_f = close.ewm(span=ema_fast, adjust=False).mean()
        ema_s = close.ewm(span=ema_slow, adjust=False).mean()
        macd = ema_f - ema_s
        macd_sig = macd.ewm(span=ema_signal, adjust=False).mean()

        # --- RSI(14) ---
        rsi_period = 14
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(alpha=1 / rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / rsi_period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-12)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # --- Bollinger Bands ---
        bb_period, bb_k = 20, 2.0
        ma_bb = close.rolling(bb_period).mean()
        sd_bb = close.rolling(bb_period).std()
        upper_bb = ma_bb + bb_k * sd_bb
        lower_bb = ma_bb - bb_k * sd_bb
        bb_perc_b = (close - lower_bb) / ((upper_bb - lower_bb) + 1e-12)
        bb_bw = (upper_bb - lower_bb) / (ma_bb + 1e-12)

        # 이벤트/상태 피처들
        # RSI 상태: -1/0/1
        rsi_hot, rsi_cold = 70, 30
        rsi_state = pd.Series(0, index=data_df.index, dtype=int)
        rsi_state[rsi >= rsi_hot] = 1
        rsi_state[rsi <= rsi_cold] = -1
        data_df["rsi_state"] = rsi_state

        # MACD 골든/데드 크로스: -1/0/1
        macd_cross = pd.Series(0, index=data_df.index, dtype=int)
        macd_cross[(macd.shift(1) < macd_sig.shift(1)) & (macd > macd_sig)] = 1
        macd_cross[(macd.shift(1) > macd_sig.shift(1)) & (macd < macd_sig)] = -1
        data_df["macd_cross"] = macd_cross

        # Bollinger 폭에 따른 상태
        bb_q_low, bb_q_high = 0.2, 0.8
        lo, hi = bb_bw.quantile([bb_q_low, bb_q_high])
        bb_state = pd.Series(0, index=data_df.index, dtype=int)
        bb_state[bb_bw <= lo] = -1
        bb_state[bb_bw >= hi] = 1
        data_df["bb_state"] = bb_state
        data_df["bb_perc_b"] = bb_perc_b

        # 나중에 action/explain용으로 쓸 수 있게 다음 종가도 붙여둠
        data_df["close_next"] = data_df["close"].shift(-1)

        return data_df

    def load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        self.hyperparams = payload.get("hyperparams", {})

        # seq_len 복원
        self.seq_len = payload.get("seq_len", self.hyperparam_schema["seq_len"]["default"])
        self.inference_window = self.seq_len + 50

        # 정규화 통계 복원
        feat_mean = payload.get("feat_mean", None)
        feat_std = payload.get("feat_std", None)
        self.feat_mean = np.array(feat_mean, dtype=np.float32) if feat_mean is not None else None
        self.feat_std = np.array(feat_std, dtype=np.float32) if feat_std is not None else None

        # 하이퍼파라 기반 모델 구조 재생성
        d_model = int(self._get_hyperparams("d_model"))
        nhead = int(self._get_hyperparams("nhead"))
        num_layers = int(self._get_hyperparams("num_layers"))
        ff = int(self._get_hyperparams("ff"))
        dropout = float(self._get_hyperparams("dropout"))

        input_size = len(self.feature_cols)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = TransformerModel(
            input_size=input_size,
            d_model=d_model,
            num_layers=num_layers,
            nhead=nhead,
            dim_feedforward=ff,
            dropout=dropout,
        ).to(self.device)

        # state_dict 복원
        state_dict_serializable = payload["state_dict"]
        state_dict = {k: torch.tensor(v) for k, v in state_dict_serializable.items()}
        self.model.load_state_dict(state_dict)

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
            "seq_len": self.seq_len,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)