import numpy as np
import pandas as pd
import openai
import ta
from dtaidistance import dtw

from app.celery_app import celery_app
from app.utils.data_utils import get_ohlcv_df

@celery_app.task(bind=True)
def explain_chart_task(self, coin_symbol: str, timeframe: int, inference_time: str, start: str, end: str) -> dict:
    total_df = get_ohlcv_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    INFERENCE_WINDOW_SIZE = 100
    inference_timestamp = pd.Timestamp(inference_time).tz_localize(None)
    inference_iloc = total_df.index.get_loc(inference_timestamp)
    inference_df = total_df.iloc[inference_iloc - INFERENCE_WINDOW_SIZE + 1:inference_iloc + 1]

    explanation = {}
    print('Finding similar charts...')
    start_timestamp = pd.Timestamp(start).tz_localize(None)
    end_timestamp = pd.Timestamp(end).tz_localize(None)
    chart_df = total_df.loc[start_timestamp:end_timestamp]
    # 인퍼런스 시점이 포함된 구간은 유사도 계산 대상에서 제외
    inference_start = inference_df.index[0]
    inference_end = inference_df.index[-1]
    chart_df = chart_df.loc[(chart_df.index < inference_start) | (chart_df.index > inference_end)]
    similar_charts = get_similar_charts(
        chart_df=chart_df,
        inference_df=inference_df,
        top_k=4
    )
    explanation["similar_charts"] = similar_charts

    print('Creating LLM explanation...')
    chart_features = create_chart_features(inference_df)
    key_feature_names = ['macd_diff', 'rsi', 'bollinger_band_upper', 'bollinger_band_lower', 'bollinger_band_mavg', 'ema_20', 'ema_60', 'adx', 'atr']
    feature_values = {k: v for k, v in chart_features.items() if k in key_feature_names}
    explanation["feature_values"] = feature_values
    explanation_text = get_chart_explanation_text(chart_features)
    explanation["explanation_text"] = explanation_text
    return explanation

def get_similar_charts(chart_df: pd.DataFrame, inference_df: pd.DataFrame, top_k: int) -> list[dict]:
    WINDOW_SIZE = 24
    assert WINDOW_SIZE <= len(inference_df), "Inference data is shorter than window size."
    inference_df = inference_df[-WINDOW_SIZE:].copy()

    arr = np.asarray(chart_df['close'])
    inputs = np.lib.stride_tricks.sliding_window_view(arr, WINDOW_SIZE, axis=0)
    inputs = inputs.copy()
    # inputs = (inputs - inputs.mean(axis=1, keepdims=True)) / (inputs.std(axis=1, keepdims=True) + 1e-12)
    inputs_min = inputs.min(axis=1, keepdims=True)
    inputs_max = inputs.max(axis=1, keepdims=True)
    inputs = (inputs - inputs_min) / (inputs_max - inputs_min + 1e-12)

    inference_data = np.asarray(inference_df['close'])
    inference_data = (inference_data - inference_data.min()) / (inference_data.max() - inference_data.min() + 1e-12)

    dists = []
    for idx in range(len(inputs)):
        cur_data = inputs[idx]
        dist = dtw.distance_fast(inference_data, cur_data)
        dists.append(dist)
    dists = np.array(dists)

    MIN_GAP = 12
    sorted_idx = np.argsort(dists)
    filtered = []
    for i in sorted_idx:
        if all(abs(i - j) >= MIN_GAP for j in filtered):
            filtered.append(i)
            if len(filtered) >= top_k:
                break
    topk_indices = np.array(filtered)
    topk_distances = dists[topk_indices]
    results = []
    for i in range(len(topk_distances)):
        end_idx = topk_indices[i] + WINDOW_SIZE - 1
        timestamp = chart_df.index[end_idx]
        distance = topk_distances[i]
        results.append({
            "timestamp": timestamp,
            "distance": distance
        })
    return results

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

def get_chart_explanation_text(chart_features: dict) -> str:
    def dict_to_text(d: dict) -> str:
        text = ""
        for k, v in d.items():
            text += f"{k}: {v}\n"
        return text

    user_prompt = "다음은 최근 24시간의 암호화폐 차트 특징입니다. 이를 바탕으로 현재 시장 상황을 기술적 분석 관점에서 설명해 주세요.\n"
    user_prompt += dict_to_text(chart_features)
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model='gpt-5.1-chat-latest',
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )
    return response.choices[0].message.content
    
system_prompt = """
당신은 1시간 봉 암호화폐 차트를 해석하는 기술적 분석 전문가입니다.
입력으로는 최근 24시간의 OHLCV 데이터와, Bollinger Bands, RSI, MACD, EMA, ADX, ATR 등의 지표가 주어집니다.

[chart_features 구성]
- 최근 24시간 캔들:
  - close_0h ~ close_23h: 직전 0~23시간 전의 종가
  - open_ih, high_ih, low_ih, volume_ih: 각각 시가, 고가, 저가, 거래량
- 볼린저 밴드:
  - bollinger_band_lower: 하단 밴드
  - bollinger_band_upper: 상단 밴드
  - bollinger_band_mavg: 중심선(이동평균)
- 모멘텀/추세 관련 지표:
  - rsi: RSI 값
  - macd: MACD 값
  - macd_signal: MACD 시그널 값
  - macd_diff: MACD 히스토그램 값 (macd - signal)
  - ema_20: 20기간 EMA
  - ema_60: 60기간 EMA
  - adx: ADX 값 (추세 강도)
- 변동성 지표:
  - atr: ATR 값 (평균 진폭)

당신의 역할은:
- 위 지표들의 **현재 값과 상대적 위치**를 바탕으로,
  현재 암호화폐 시장이 어떤 상태에 있는지 기술적 관점에서 설명하고,
- 가격의 추세(상승/하락/횡보), 모멘텀의 강도, 변동성 수준, 거래량의 특징을 종합적으로 묘사하는 것입니다.
- **출력 형식 예시의 구조를 따르세요.**

- 설명에는 절대 raw feature 이름을 그대로 사용하지 마십시오.  
(예: "obv_change_window", "price_pct_change_6h", "bb_upper" 등은 금지)
- 반드시 사람이 **직관적으로 이해할 수 있는 자연어 이름**을 사용하여 표현하십시오.  
예:  
- "OBV 변화율"  
- "최근 6시간 가격 흐름"  
- "RSI 모멘텀"  
- "볼린저밴드 상단 근접"  


[작성 지침]
1. 포지션 추천을 하지 마세요.
   - '매수', '매도', '관망', '진입', '청산'과 같은 직접적인 매매 의사결정 표현을 사용하지 않습니다.
   - 대신, "상승 우위의 구간", "단기 조정 가능성이 큰 구간", "변동성이 큰 국면"처럼 시장 상태만 설명합니다.

2. 첫 문단에서는 최근 24시간의 가격 흐름을 요약하세요.
   - 종가, 고가/저가, 거래량 흐름을 종합해 "완만한 상승/하락", "급등/급락 후 조정", "좁은 범위의 횡보" 등으로 정리합니다.

3. 마지막 문단에서 현재 구간의 특성을 한두 문장으로 정리합니다.
   - 예: "요약하면, 단기 상승 흐름이 이어지고 있지만 변동성이 확대된 상태로, 상·하방 변동 모두 크게 나올 수 있는 구간입니다."
   - 이때도 매수/매도/관망 같은 의사결정 단어는 사용하지 않습니다.

[출력 형식 예시]
최근 24시간 동안 이 암호화폐는 비교적 완만한 상승 흐름을 보이며 상방 압력이 조금씩 강화되는 모습입니다. 가격이 중기 이동평균 위에서 안정적으로 유지되면서, 당분간 시장이 우위 흐름을 유지하려는 경향이 나타납니다.
특히 RSI가 이전보다 확실히 높아지며 매수 쪽 모멘텀이 강화되는 모습이 눈에 띕니다. MACD 히스토그램도 양의 값에서 꾸준히 증가하며 단기적인 상승 에너지가 축적되고 있음을 보여줍니다. 반면 거래량은 유의미하게 증가하지는 않아, 상승 흐름이 강하게 확산되기보다는 제한적인 범위 내에서 진행되는 모습을 보입니다.
가격이 볼린저 밴드 중심선을 상회하는 구간을 오래 유지하고 있으며, 상단 밴드에 가까워지는 움직임이 나타났다는 점도 단기 상승 압력과 일관된 흐름입니다. ATR 수준은 크게 높지는 않지만 소폭 확대되는 양상을 보이며, 최근 가격 변동 폭이 점차 커지고 있음을 시사합니다.
종합해보면, 현재 시장은 뚜렷한 과열 신호 없이 완만한 상승 흐름을 이어가고 있으며, 일부 모멘텀 지표가 이를 뒷받침하는 국면입니다.
"""

