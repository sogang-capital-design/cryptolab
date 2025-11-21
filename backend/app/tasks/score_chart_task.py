import numpy as np
import pandas as pd
import ta
import openai
import json

from app.celery_app import celery_app
from app.utils.data_utils import get_ohlcv_df

@celery_app.task(bind=True)
def score_chart_task(self, coin_symbol: str, timeframe: int, inference_time: str, history_window: int) -> dict:
    total_df = get_ohlcv_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    inference_timestamp = pd.Timestamp(inference_time).tz_localize(None)
    inference_iloc = total_df.index.get_loc(inference_timestamp)
    inference_df = total_df.iloc[inference_iloc - history_window + 1:inference_iloc + 1]
    system_prompt = _build_system_prompt()
    chart_features = create_chart_features(inference_df)
    additional_chart_features = create_additional_chart_features(inference_df)
    chart_features.update(additional_chart_features)
    user_prompt = _build_user_prompt(chart_features)

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model='gpt-5.1-chat-latest',
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )
    json_response = response.choices[0].message.content
    chart_score_dict = json.loads(json_response)
    return chart_score_dict

def _build_system_prompt() -> str:
    system_prompt = """
당신은 금융 차트 분석용 정량 판단 모델입니다.  
입력으로 주어지는 기술적 지표(feature 값)들과 지표 설명(feature definitions)을 기반으로  
시장의 상황을 정확하게 해석하고 다음 5개의 점수를 반드시 정량적으로 산출해야 합니다.

당신의 목표는 아래 5가지 지표에 대해
1) 일관된 방식으로 정량 점수를 계산하고
2) 그 점수에 대한 직관적인 해설을 2~3문장으로 제시하는 것입니다.

[필수로 계산해야 할 5가지 지표]

1. volatility_risk (0~100)
   - 변동성의 크기. 클수록 위험이 큰 상태.

2. overextension (-100~100)
   - 과매도(-100) ~ 중립(0) ~ 과열(+100)

3. directionality (-100~100)
   - 하락 우위(-100) ~ 횡보(0) ~ 상승 우위(+100)

4. breakout_strength (0~100)
   - 가격이 기존 레인지를 벗어나 움직이려는 힘의 크기

5. accumulation_distribution (-100~100)
   - 분산(매도 압력) -100 ~ 중립(0) ~ 매집(매수 압력) +100

[점수 계산 규칙]

- 항상 feature definition에 명시된 수식적 의미나 방향성(양수/음수 해석 등)을 그대로 따라야 합니다.
- 동일한 입력이 들어오면 항상 비슷한 범위의 점수가 나오도록 일관되게 판단해야 합니다.
- 각 스코어의 부호와 크기는 반드시 지표의 방향성과 논리적으로 일치해야 합니다.

[설명(explanation) 작성 규칙]

- 설명에는 절대 raw feature 이름을 그대로 사용하지 마십시오.  
  (예: "obv_change_window", "price_pct_change_6h", "bb_upper" 등은 금지)
- 반드시 사람이 **직관적으로 이해할 수 있는 자연어 이름**을 사용하여 표현하십시오.  
  예:  
    - "OBV 변화율"  
    - "최근 6시간 가격 흐름"  
    - "RSI 모멘텀"  
    - "볼린저밴드 상단 근접"  

- 각 지표마다 "설명(explanation)"을 1~2문장으로 작성합니다.
- 설명은 한국어로 작성합니다.
- 설명에는 반드시 어떤 feature들이 주요 근거였는지 언급해야 합니다.
  예: "RSI가 70 이상이고, 볼린저밴드 상단 근처에 위치하여 과열 구간에 가깝습니다."
- 문장은 짧고 직관적으로, 투자자가 바로 이해할 수 있는 수준으로 작성합니다.
- 점수와 상충되는 표현을 사용하지 마십시오.
  - 예: overextension 점수가 +80인데 "과도한 과매도는 보이지 않습니다" 같은 문구는 금지.
- feature definition에 나오는 수식 또는 방향성을 거스르는 설명은 금지합니다.
- 모델이 임의로 새로운 지표나 데이터를 만들어내지 말고, 주어진 feature들만 근거로 사용하십시오.

[최종 출력 형식]

최종 출력은 반드시 아래 JSON 스키마를 따라야 합니다.

{
  "volatility_risk": {
    "score": <0-100 number>,
    "explanation": "<1~2문장 한국어 문자열>"
  },
  "overextension": {
    "score": <-100~100 number>,
    "explanation": "<1~2문장 한국어 문자열>"
  },
  "directionality": {
    "score": <-100~100 number>,
    "explanation": "<1~2문장 한국어 문자열>"
  },
  "breakout_strength": {
    "score": <0-100 number>,
    "explanation": "<1~2문장 한국어 문자열>"
  },
  "accumulation_distribution": {
    "score": <-100~100 number>,
    "explanation": "<1~2문장 한국어 문자열>"
  }
}

중요:
- 반드시 유효한 JSON만 출력하십시오.
- 키와 문자열은 모두 큰따옴표(")를 사용하십시오.
- JSON 외의 어떤 텍스트(설명, 자연어, 코드 블록 등)도 출력하지 마십시오.
- JSON 외 출력은 실패로 간주됩니다.
"""
    return system_prompt

def _build_user_prompt(chart_features: dict) -> str:
    user_prompt = "다음은 암호화폐 차트의 기술적 지표(feature) 값들과 각 지표의 정의입니다.\n"
    user_prompt += "이를 바탕으로 시장 상황을 해석하고 5가지 점수를 설명과 함께 산출해 주세요.\n\n"
    for k, v in chart_features.items():
        user_prompt += f"- {k}: {v}\n"
    user_prompt += "\n[Feature Definitions]\n"
    all_feature_description_dict = {**feature_description_dict, **additional_feature_description_dict}
    for k, v in all_feature_description_dict.items():
        user_prompt += f"- {k}: {v}\n"
    return user_prompt

def create_chart_features(inference_df: pd.DataFrame) -> dict:
    chart_features = {}
    for i in range(24):
        row = inference_df.iloc[-i-1]
        chart_features[f"close_{i}h"] = float(row['close'])
        chart_features[f"volume_{i}h"] = float(row['volume'])
        chart_features[f"high_{i}h"] = float(row['high'])
        chart_features[f"low_{i}h"] = float(row['low'])
        chart_features[f"open_{i}h"] = float(row['open'])

    bb = ta.volatility.BollingerBands(inference_df['close'])
    chart_features['bollinger_band_lower'] = float(bb.bollinger_lband().iloc[-1])
    chart_features['bollinger_band_upper'] = float(bb.bollinger_hband().iloc[-1])
    chart_features['bollinger_band_mavg'] = float(bb.bollinger_mavg().iloc[-1])
    chart_features['rsi'] = float(ta.momentum.RSIIndicator(inference_df['close']).rsi().iloc[-1])
    macd = ta.trend.MACD(inference_df['close'])
    chart_features['macd'] = float(macd.macd().iloc[-1])
    chart_features['macd_signal'] = float(macd.macd_signal().iloc[-1])
    chart_features['macd_diff'] = float(macd.macd_diff().iloc[-1])

    chart_features['ema_20'] = float(ta.trend.EMAIndicator(inference_df['close'], window=20).ema_indicator().iloc[-1])
    chart_features['ema_60'] = float(ta.trend.EMAIndicator(inference_df['close'], window=60).ema_indicator().iloc[-1])

    chart_features['adx'] = float(ta.trend.ADXIndicator(
        high=inference_df['high'],
        low=inference_df['low'],
        close=inference_df['close']
    ).adx().iloc[-1])
    chart_features['atr'] = float(ta.volatility.AverageTrueRange(
        high=inference_df['high'],
        low=inference_df['low'],
        close=inference_df['close']
    ).average_true_range().iloc[-1])
    return chart_features

def create_additional_chart_features(inference_df: pd.DataFrame) -> dict:
    features: dict[str, float] = {}

    # 최신 값들
    last = inference_df.iloc[-1]
    close = inference_df["close"]
    high = inference_df["high"]
    low = inference_df["low"]
    open_ = inference_df["open"]
    volume = inference_df["volume"]

    close_now = float(last["close"])
    eps = 1e-12

    returns = close.pct_change().dropna()
    if len(returns) > 0:
        realized_vol_24 = returns.tail(24).std()
    else:
        realized_vol_24 = np.nan

    atr_series = ta.volatility.AverageTrueRange(
        high=high,
        low=low,
        close=close
    ).average_true_range()
    atr_last = float(atr_series.iloc[-1])
    atr_pct = float(atr_last / (close_now + eps))

    bb = ta.volatility.BollingerBands(close)
    bb_l = float(bb.bollinger_lband().iloc[-1])
    bb_u = float(bb.bollinger_hband().iloc[-1])
    bb_m = float(bb.bollinger_mavg().iloc[-1])
    bb_width_pct = float((bb_u - bb_l) / (abs(bb_m) + eps))

    features["realized_vol_24"] = float(realized_vol_24)
    features["atr_pct"] = atr_pct
    features["bollinger_band_width_pct"] = bb_width_pct

    ema20_series = ta.trend.EMAIndicator(close, window=20).ema_indicator()
    ema60_series = ta.trend.EMAIndicator(close, window=60).ema_indicator()
    ema20_last = float(ema20_series.iloc[-1])
    ema60_last = float(ema60_series.iloc[-1])

    dist_from_upper_band_pct = float((close_now - bb_u) / (abs(bb_m) + eps))
    dist_from_lower_band_pct = float((close_now - bb_l) / (abs(bb_m) + eps))
    dist_from_ema20_pct = float((close_now - ema20_last) / (abs(ema20_last) + eps))
    dist_from_ema60_pct = float((close_now - ema60_last) / (abs(ema60_last) + eps))

    features["dist_from_upper_band_pct"] = dist_from_upper_band_pct
    features["dist_from_lower_band_pct"] = dist_from_lower_band_pct
    features["dist_from_ema20_pct"] = dist_from_ema20_pct
    features["dist_from_ema60_pct"] = dist_from_ema60_pct

    def safe_ret(lookback: int) -> float:
        if len(close) > lookback:
            past = float(close.iloc[-lookback-1])
            return float(close_now / (past + eps) - 1.0)
        return np.nan

    ret_4h = safe_ret(4)
    ret_24h = safe_ret(24)

    ema_diff_pct = float((ema20_last - ema60_last) / (abs(ema60_last) + eps))

    macd = ta.trend.MACD(close)
    macd_hist_last = float(macd.macd_diff().iloc[-1])

    features["ret_4h"] = ret_4h
    features["ret_24h"] = ret_24h
    features["ema_diff_pct"] = ema_diff_pct
    features["macd_hist_last"] = macd_hist_last

    window = min(len(inference_df), 24)
    recent = inference_df.iloc[-window:]

    range_high_24 = float(recent["high"].max())
    range_low_24 = float(recent["low"].min())

    breakout_from_high_pct = float((close_now - range_high_24) / (abs(range_high_24) + eps))
    breakout_from_low_pct = float((close_now - range_low_24) / (abs(range_low_24) + eps))

    last_high = float(last["high"])
    last_low = float(last["low"])
    last_open = float(last["open"])
    last_volume = float(last["volume"])

    full_range = max(last_high - last_low, 0.0)
    body = abs(close_now - last_open)
    upper_shadow = max(last_high - max(last_open, close_now), 0.0)
    lower_shadow = max(min(last_open, close_now) - last_low, 0.0)

    body_ratio = float(body / (full_range + eps))
    upper_shadow_ratio = float(upper_shadow / (full_range + eps))
    lower_shadow_ratio = float(lower_shadow / (full_range + eps))

    volume_mean_24 = float(recent["volume"].mean())
    volume_boost_24 = float(last_volume / (volume_mean_24 + eps))

    features["range_high_24"] = range_high_24
    features["range_low_24"] = range_low_24
    features["breakout_from_high_pct"] = breakout_from_high_pct
    features["breakout_from_low_pct"] = breakout_from_low_pct
    features["last_body_ratio"] = body_ratio
    features["last_upper_shadow_ratio"] = upper_shadow_ratio
    features["last_lower_shadow_ratio"] = lower_shadow_ratio
    features["volume_boost_24"] = volume_boost_24

    obv_series = ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    obv_last = float(obv_series.iloc[-1])
    if len(obv_series) > window:
        obv_prev = float(obv_series.iloc[-window-1])
        obv_change_window = float(obv_last - obv_prev)
    else:
        obv_change_window = np.nan

    try:
        mfi_series = ta.volume.MFIIndicator(
            high=high,
            low=low,
            close=close,
            volume=volume,
            window=14
        ).money_flow_index()
        mfi_last = float(mfi_series.iloc[-1])
    except Exception:
        mfi_last = np.nan

    recent_high = recent["high"].to_numpy(dtype=float)
    recent_low = recent["low"].to_numpy(dtype=float)
    recent_open = recent["open"].to_numpy(dtype=float)
    recent_close = recent["close"].to_numpy(dtype=float)
    recent_volume = recent["volume"].to_numpy(dtype=float)

    full_rng = np.maximum(recent_high - recent_low, 0.0)
    upper = np.maximum(recent_high - np.maximum(recent_open, recent_close), 0.0)
    lower = np.maximum(np.minimum(recent_open, recent_close) - recent_low, 0.0)

    upper_wick_vol_sum = float(((upper / (full_rng + eps)) * recent_volume).sum())
    lower_wick_vol_sum = float(((lower / (full_rng + eps)) * recent_volume).sum())

    features["obv_last"] = obv_last
    features["obv_change_window"] = obv_change_window
    features["mfi_last"] = mfi_last
    features["upper_wick_volume_sum_window"] = upper_wick_vol_sum
    features["lower_wick_volume_sum_window"] = lower_wick_vol_sum

    return features

feature_description_dict = {
    "close_{i}h": 
        "과거 i시간 전의 종가. 총 24개(hour 0~23)의 최근 가격 흐름을 제공합니다.",

    "open_{i}h":
        "과거 i시간 전의 시가.",

    "high_{i}h":
        "과거 i시간 전의 고가.",

    "low_{i}h":
        "과거 i시간 전의 저가.",

    "volume_{i}h":
        "과거 i시간 전의 거래량.",

    "bollinger_band_lower":
        "볼린저밴드 하단선 값. 가격이 밴드 하단에 가까우면 변동성 하단 압력 또는 과매도 가능.",

    "bollinger_band_upper":
        "볼린저밴드 상단선 값. 가격이 밴드 상단에 가까우면 단기 과열 또는 상단 저항 가능.",

    "bollinger_band_mavg":
        "볼린저밴드 중심선(보통 20SMA). 가격의 평균 수준을 나타냄.",

    "rsi":
        "RSI(상대강도지수). 70 이상은 과매수 경향, 30 이하이면 과매도 경향.",

    "macd":
        "MACD 값. 단기 추세 EMA와 장기 EMA의 차이로 상승/하락 모멘텀을 나타냄.",

    "macd_signal":
        "MACD 시그널 라인. MACD의 평활화 버전이며 MACD 크로스 기준선 역할.",

    "macd_diff":
        "MACD 히스토그램 값 (MACD - 시그널). 양수면 상승 모멘텀 강화, 음수면 하락 모멘텀 강화.",

    "ema_20":
        "20기간 지수이동평균. 단기 추세를 나타냄.",

    "ema_60":
        "60기간 지수이동평균. 중기 추세를 나타냄.",

    "adx":
        "ADX(평균 방향성 지수). 추세의 강도를 나타냄. 20 미만은 약한 추세, 25 이상은 뚜렷한 추세.",

    "atr":
        "Average True Range. 절대적 변동폭(진폭)의 크기. 값이 크면 변동성이 크다는 의미."
}

additional_feature_description_dict = {
    "realized_vol_24": 
        "최근 24개 종가의 수익률의 표준편차. 최근 하루 동안 가격이 얼마나 흔들렸는지를 나타냄. 값이 클수록 변동성이 높음.",

    "atr_pct":
        "ATR(평균 진폭)을 현재 종가로 나눈 값. 캔들의 절대 변동폭이 가격 대비 어느 정도 비율인지 나타냄. 값이 클수록 변동성 위험이 큼.",

    "bollinger_band_width_pct":
        "볼린저 밴드 상단과 하단의 차이를 중심선으로 나눈 비율. 밴드가 넓을수록 추세 불안정 또는 변동성 확장을 의미.",

    "dist_from_upper_band_pct":
        "현재 종가가 볼린저밴드 상단보다 얼마나 위에 있는지의 비율. 양수면 상단 돌파, 과열 가능성을 의미.",

    "dist_from_lower_band_pct":
        "현재 종가가 볼린저밴드 하단보다 얼마나 아래에 있는지의 비율. 음수면 하단 이탈, 침체 또는 과매도 신호 가능.",

    "dist_from_ema20_pct":
        "현재 가격이 EMA20보다 얼마나 위/아래에 있는지. 양수면 단기 상승 우위, 음수면 단기 하락 우위.",

    "dist_from_ema60_pct":
        "현재 가격이 EMA60보다 얼마나 위/아래에 있는지. 중단기 추세 대비 과열/침체 정도를 반영.",

    "ret_4h":
        "최근 4시간 동안의 종가 수익률. 단기 가격 방향성을 나타냄.",

    "ret_24h":
        "최근 24시간 동안의 종가 수익률. 최근 하루 동안의 상승/하락 흐름.",

    "ema_diff_pct":
        "EMA20과 EMA60의 차이를 EMA60 대비 비율로 나타낸 값. 양수면 상승 쪽 기울기 우세, 음수면 하락 기울기 우세.",

    "macd_hist_last":
        "MACD 히스토그램의 최근 값. 양수면 상승 모멘텀 강화, 음수면 하락 모멘텀 강화.",

    "range_high_24":
        "최근 24개 캔들 중 가장 높은 고가. 브레이크아웃 기준점으로 사용.",

    "range_low_24":
        "최근 24개 캔들 중 가장 낮은 저가. 하방 이탈 기준점.",

    "breakout_from_high_pct":
        "최근 고점(range_high_24) 대비 현재 종가가 얼마나 위에 있는지를 비율로 표시. 양수면 상방 돌파.",

    "breakout_from_low_pct":
        "최근 저점(range_low_24) 대비 현재 종가가 얼마나 아래에 있는지를 비율로 표시. 음수면 하방 돌파.",

    "last_body_ratio":
        "가장 최근 캔들의 몸통 크기를 전체 캔들 길이로 나눈 값. 1에 가까울수록 방향성 있는 강한 움직임.",

    "last_upper_shadow_ratio":
        "최근 캔들의 윗꼬리 길이를 전체 길이로 나눈 값. 값이 크면 상방 저항 또는 가짜 돌파 가능성.",

    "last_lower_shadow_ratio":
        "최근 캔들의 아랫꼬리 길이를 전체 길이로 나눈 값. 값이 크면 매수 지지 또는 하단 매집 가능성.",

    "volume_boost_24":
        "최근 캔들 거래량을 최근 24개 평균 거래량으로 나눈 값. 값이 크면 돌파 움직임의 신뢰도가 높음.",

    "obv_last":
        "OBV(거래량 누적) 지표의 최신 값. 매수세/매도세 흐름을 반영.",

    "obv_change_window":
        "최근 24개 구간 동안 OBV가 얼마나 증가/감소했는지. 양수는 매집, 음수는 분산을 의미.",

    "mfi_last":
        "MFI(자금 흐름 지표)의 최근 값. 거래량과 가격을 함께 반영한 매수/매도 압력 지표.",

    "upper_wick_volume_sum_window":
        "최근 24개 캔들에서 윗꼬리 비율 x 거래량을 모두 더한 값. 높으면 분산(매도 압력) 신호.",

    "lower_wick_volume_sum_window":
        "최근 24개 캔들에서 아랫꼬리 비율 x 거래량 합산. 높으면 매집(매수 압력) 신호."
}

