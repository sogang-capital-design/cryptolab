import numpy as np
import pandas as pd
import openai
import ta
import json

from app.celery_app import celery_app
from app.strategies.LightGBM_strategy import LightGBMStrategy
from app.utils.data_utils import get_feature_texts, get_total_df_online, get_prompt
from app.utils.cache_utils import cache_task_result

@celery_app.task(bind=True)
@cache_task_result(prefix="explain_chart")
def explain_chart_task(self, coin_symbol: str, timeframe: int, inference_time: str) -> dict:
    INFERENCE_WINDOW_SIZE = 100
    inference_ts = pd.Timestamp(inference_time)
    if inference_ts.tz is None:
        inference_ts = inference_ts.tz_localize("UTC")
    start_time = inference_ts - pd.Timedelta(hours=INFERENCE_WINDOW_SIZE)
    end_time = inference_ts
    inference_df = get_total_df_online(coin_symbol, start_time, end_time)
    
    explanation = {}
    print('Creating LLM explanation...')
    chart_features = create_chart_features(inference_df)
    filtered_feature_names = get_filtered_chart_features(chart_features)
    filtered_chart_features = {k: v for k, v in chart_features.items() if k in filtered_feature_names}

    # feature 설명 추가
    chart_feature_texts = get_feature_texts('LightGBM_model')
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
                    feature_obj['interpretation'] = f"{timeframe}시간 전 대비 {base_info['display_name']}의 변화율입니다."
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
    model = LightGBMStrategy()
    X, y = model._get_X_and_y(inference_df)
    model_features = X.iloc[-1]
    for column in X.columns:
        if ('pct_change_3h' not in column and 'pct_change_12h' not in column
            and np.isfinite(model_features[column])):
            chart_features[column] = model_features[column]
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
    chart_feature_description_dict = get_feature_texts('LightGBM_model')
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
    chart_feature_description_dict = get_feature_texts('LightGBM_model')
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
    result = response.choices[0].message.content
    print(f"[LLM Response] Length: {len(result) if result else 0}, Content preview: {result[:100] if result else 'EMPTY'}")
    if not result or len(result.strip()) == 0:
        print("[WARNING] Empty explanation_text returned from LLM!")
        return "설명을 생성할 수 없습니다. 다시 시도해주세요."
    return result