import numpy as np
import pandas as pd
import openai
import ta
import json

from app.celery_app import celery_app
from app.utils.data_utils import get_feature_texts, get_ohlcv_df, get_onchain_df, get_prompt

@celery_app.task(bind=True)
def explain_chart_task(self, coin_symbol: str, timeframe: int, inference_time: str) -> dict:
    ohlcv_df = get_ohlcv_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    onchain_df = get_onchain_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    total_df = pd.merge(ohlcv_df, onchain_df, left_index=True, right_index=True, how='inner')
    INFERENCE_WINDOW_SIZE = 100
    inference_timestamp = pd.Timestamp(inference_time).tz_localize(None)
    inference_iloc = total_df.index.get_loc(inference_timestamp)
    inference_df = total_df.iloc[inference_iloc - INFERENCE_WINDOW_SIZE + 1:inference_iloc + 1]

    explanation = {}
    print('Creating LLM explanation...')
    chart_features = create_chart_features(inference_df)
    filtered_feature_names = get_filtered_chart_features(chart_features)
    filtered_chart_features = {k: v for k, v in chart_features.items() if k in filtered_feature_names}

    # feature 설명 추가
    chart_feature_texts = get_feature_texts('chart')
    feature_values_with_metadata = {}
    for feature_name, value in filtered_chart_features.items():
        feature_obj = {
            'value': value
        }
        if feature_name in chart_feature_texts:
            feature_info = chart_feature_texts[feature_name]
            feature_obj['display_name'] = feature_info['display_name']
            feature_obj['interpretation'] = feature_info['interpretation']
        else:
            # pct_change feature의 경우 동적으로 설명 생성
            if '_pct_change_' in feature_name:
                # feature_name 형식: "some_feature_pct_change_1h"
                parts = feature_name.rsplit('_pct_change_', 1)
                base_feature = parts[0]
                timeframe = parts[1].replace('h', '')

                if base_feature in chart_feature_texts:
                    base_info = chart_feature_texts[base_feature]
                    feature_obj['display_name'] = f"{base_info['display_name']} ({timeframe}시간 변화율)"
                    feature_obj['interpretation'] = f"{timeframe}시간 전 대비 {base_info['display_name']}의 변화율입니다. {base_info['interpretation']}"
                else:
                    feature_obj['display_name'] = f"{base_feature} ({timeframe}시간 변화율)"
                    feature_obj['interpretation'] = f"{timeframe}시간 전 대비 변화율"
        feature_values_with_metadata[feature_name] = feature_obj

    explanation["feature_values"] = feature_values_with_metadata
    explanation_text = get_chart_explanation_text(chart_features)
    explanation["explanation_text"] = explanation_text

    # Debug: 첫 번째 feature의 구조 확인
    if feature_values_with_metadata:
        first_key = next(iter(feature_values_with_metadata))
        print(f"Sample feature structure: {first_key} = {feature_values_with_metadata[first_key]}")

    return explanation

def create_chart_features(inference_df: pd.DataFrame) -> dict:
    chart_features = {}
    inference_df.drop(columns=['price_usd'], inplace=True, errors='ignore')
    price = inference_df["close"].astype(float)
    volume = inference_df["volume"].astype(float)

    window = 24  # 최근 24시간 기준
    # 1) 가격 기반 실현 변동성 (volatility_risk용)
    returns_1h = price.pct_change()
    last_24_ret = returns_1h.iloc[-window:]
    chart_features["realized_vol_24h"] = float(last_24_ret.std())

    # 2) 최근 24h 레인지 대비 현재 위치 (breakout_strength용)
    recent_prices = price.iloc[-window:]
    last_price = float(recent_prices.iloc[-1])
    high_24h = float(recent_prices.max())
    low_24h = float(recent_prices.min())

    chart_features["dist_from_24h_high"] = float(last_price / high_24h - 1.0)
    chart_features["dist_from_24h_low"] = float(last_price / low_24h - 1.0)

    # 3) 거래량 강도 인덱스 (breakout/매집·분산 보조용)
    recent_vol = volume.iloc[-window:]
    mean_vol_24h = float(recent_vol.mean())
    last_vol = float(recent_vol.iloc[-1])
    chart_features["volume_intensity_24h"] = float(last_vol / mean_vol_24h)

    inference_df = inference_df.drop(columns=["open", "high", "low", "volume"])
    for feature_name in inference_df.columns:
        chart_features[feature_name] = float(inference_df[feature_name].iloc[-1])
    time_diffs = [1, 6, 48]
    for time_diff in time_diffs:
        for col in inference_df.columns:
            value = float(inference_df[col].pct_change(time_diff).iloc[-1])
            if value == np.inf or value == -np.inf:
                continue
            chart_features[f"{col}_pct_change_{time_diff}h"] = value


    bb = ta.volatility.BollingerBands(inference_df["close"])
    chart_features["bollinger_band_lower"] = float(bb.bollinger_lband().iloc[-1])
    chart_features["bollinger_band_upper"] = float(bb.bollinger_hband().iloc[-1])
    chart_features["bollinger_band_mavg"] = float(bb.bollinger_mavg().iloc[-1])

    chart_features["rsi"] = float(ta.momentum.RSIIndicator(inference_df["close"]).rsi().iloc[-1])
    macd = ta.trend.MACD(inference_df["close"])
    chart_features["macd"] = float(macd.macd().iloc[-1])
    chart_features["macd_signal"] = float(macd.macd_signal().iloc[-1])
    chart_features["macd_diff"] = float(macd.macd_diff().iloc[-1])

    chart_features["ema_20"] = float(
        ta.trend.EMAIndicator(inference_df["close"], window=20).ema_indicator().iloc[-1]
    )
    chart_features["ema_60"] = float(
        ta.trend.EMAIndicator(inference_df["close"], window=60).ema_indicator().iloc[-1]
    )
    return chart_features

def dict_to_text(d: dict) -> str:
    text = ""
    for k, v in d.items():
        text += f"{k}: {v}\n"
    return text

def feature_dict_to_text(d: dict) -> str:
    text = ""
    for k, inner_d in d.items():
        name, interp = inner_d['display_name'], inner_d['interpretation']
        text += f"{k} ({name}): {interp}\n"
    return text

def get_filtered_chart_features(chart_features: dict) -> dict:
    chart_features = {k: v for k, v in chart_features.items() if "_pct_change_1h" in k}
    system_prompt = get_prompt("filter_features")
    user_prompt = "다음은 최근 24시간의 암호화폐 차트 특징입니다. 중요한 feature만 선택해주세요.\n"
    user_prompt += dict_to_text(chart_features)
    chart_feature_description_dict = get_feature_texts('chart')
    user_prompt += f"각 feature의 정의는 아래와 같습니다.\n"
    user_prompt += feature_dict_to_text(chart_feature_description_dict)
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model='gpt-5.1-chat-latest',
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )
    output_raw = response.choices[0].message.content
    output = json.loads(output_raw)
    return output['selected_features']

def get_chart_explanation_text(chart_features: dict) -> str:

    system_prompt = get_prompt("explain_chart")
    user_prompt = "다음은 최근 24시간의 암호화폐 차트 특징입니다. 이를 바탕으로 현재 시장 상황을 기술적 분석 관점에서 설명해 주세요.\n"
    user_prompt += dict_to_text(chart_features)
    chart_feature_description_dict = get_feature_texts('chart')
    filtered_chart_feature_description_dict = {k: v for k, v in chart_feature_description_dict.items() if k in chart_features}
    user_prompt += f"각 feature의 정의는 아래와 같습니다.\n"
    user_prompt += feature_dict_to_text(filtered_chart_feature_description_dict)
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model='gpt-5.1-chat-latest',
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )
    return response.choices[0].message.content