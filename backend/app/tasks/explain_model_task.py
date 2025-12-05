import numpy as np
import pandas as pd
import openai
from scipy.stats import laplace

from app.celery_app import celery_app
from app.utils.model_load_utils import get_strategy_class, get_param_path
from app.utils.data_utils import get_total_df, get_total_df_online, get_model_meta_info, get_prompt, get_feature_texts
from app.utils.cache_utils import cache_task_result

@celery_app.task(bind=True)
@cache_task_result(prefix="explain_model")
def explain_model_task(self, model_name:str, coin_symbol: str, timeframe: int, inference_time: str) -> dict:
    print(f'[explain_task] model={model_name}, symbol={coin_symbol}, tf={timeframe}')
    MODEL_NAME = model_name
    PARAM_NAME = f"{coin_symbol}_{timeframe}m"
    TRAIN_START = "2024-01-01 00:00:00"
    TRAIN_END = "2025-01-01 00:00:00"
    total_df = get_total_df(coin_symbol)
    strategy_class = get_strategy_class(MODEL_NAME)
    print(f'Loaded strategy class: {strategy_class.__name__}')
    inference_window = strategy_class.inference_window
    strategy_instance = strategy_class()

    params_path = get_param_path(MODEL_NAME, PARAM_NAME)
    strategy_instance.load(params_path)

    train_start_timestamp = pd.Timestamp(TRAIN_START, tz="UTC")
    train_start_timestamp -= pd.Timedelta(minutes=timeframe)
    train_end_timestamp = pd.Timestamp(TRAIN_END, tz="UTC")
    train_df = total_df.loc[train_start_timestamp:train_end_timestamp]

    INFERENCE_WINDOW_SIZE = 100
    inference_ts = pd.Timestamp(inference_time)
    if inference_ts.tz is None:
        inference_ts = inference_ts.tz_localize("UTC")
    start_time = inference_ts - pd.Timedelta(hours=INFERENCE_WINDOW_SIZE)
    end_time = inference_ts
    inference_df = get_total_df_online(coin_symbol, start_time, end_time)

    print('Creating SHAP values...')
    explanation = strategy_instance.explain(
        train_df=train_df,
        inference_df=inference_df
    )
    prediction_value = explanation.pop("prediction", 0.0)
    print(f'Prediction value: {prediction_value}')

    # feature 설명 추가
    model_feature_texts = get_feature_texts(f'{model_name}_model')

    # shap_values에 메타데이터 추가
    shap_values_with_metadata = {}
    for feature_name, value in explanation["shap_values"].items():
        feature_obj = {'value': value}
        if feature_name in model_feature_texts:
            feature_info = model_feature_texts[feature_name]
            feature_obj['display_name'] = feature_info['display_name']
            feature_obj['interpretation'] = feature_info['interpretation']
        else:
            # pct_change feature의 경우 동적으로 설명 생성
            if '_pct_change_' in feature_name:
                parts = feature_name.rsplit('_pct_change_', 1)
                base_feature = parts[0]
                timeframe = parts[1].replace('h', '')

                if base_feature in model_feature_texts:
                    base_info = model_feature_texts[base_feature]
                    feature_obj['display_name'] = f"{base_info['display_name']} ({timeframe}시간 변화율)"
                    feature_obj['interpretation'] = f"{timeframe}시간 전 대비 {base_info['display_name']}의 변화율입니다. {base_info['interpretation']}"
                else:
                    feature_obj['display_name'] = f"{base_feature} ({timeframe}시간 변화율)"
                    feature_obj['interpretation'] = f"{timeframe}시간 전 대비 변화율"
        shap_values_with_metadata[feature_name] = feature_obj
    explanation["shap_values"] = shap_values_with_metadata

    # feature_values에 메타데이터 추가
    feature_values_with_metadata = {}
    for feature_name, value in explanation["feature_values"].items():
        feature_obj = {'value': value}
        if feature_name in model_feature_texts:
            feature_info = model_feature_texts[feature_name]
            feature_obj['display_name'] = feature_info['display_name']
            feature_obj['interpretation'] = feature_info['interpretation']
        else:
            # pct_change feature의 경우 동적으로 설명 생성
            if '_pct_change_' in feature_name:
                parts = feature_name.rsplit('_pct_change_', 1)
                base_feature = parts[0]
                timeframe = parts[1].replace('h', '')

                if base_feature in model_feature_texts:
                    base_info = model_feature_texts[base_feature]
                    feature_obj['display_name'] = f"{base_info['display_name']} ({timeframe}시간 변화율)"
                    feature_obj['interpretation'] = f"{timeframe}시간 전 대비 {base_info['display_name']}의 변화율입니다. {base_info['interpretation']}"
                else:
                    feature_obj['display_name'] = f"{base_feature} ({timeframe}시간 변화율)"
                    feature_obj['interpretation'] = f"{timeframe}시간 전 대비 변화율"
        feature_values_with_metadata[feature_name] = feature_obj
    explanation["feature_values"] = feature_values_with_metadata

    meta_info = get_model_meta_info(
        model_name=MODEL_NAME,
        coin_symbol=coin_symbol,
        timeframe=timeframe,
    )

    mean, std = meta_info["mean"], meta_info["std"]
    def prediction_percentile_func(pred: float) -> float:
        percentile = laplace.cdf(pred, loc=mean, scale=std / np.sqrt(2)) * 100
        percentile = 100 - percentile  # 뒤집기
        return percentile
    prediction_percentile = prediction_percentile_func(prediction_value)

    explanation["prediction_percentile"] = prediction_percentile
    if prediction_percentile <= 15:
        explanation["recommendation"] = "Buy"
    elif prediction_percentile <= 30:
        explanation["recommendation"] = "Weak buy"
    elif prediction_percentile <= 70:
        explanation["recommendation"] = "Hold"
    elif prediction_percentile <= 85:
        explanation["recommendation"] = "Weak sell"
    else:
        explanation["recommendation"] = "Sell"

    print('Finding reference training data...')
    reference_charts = strategy_instance.get_reference_train_data(
        train_df=train_df,
        inference_df=inference_df,
        top_k=5
    )
    explanation["reference_charts"] = reference_charts

    print('Creating LLM explanation...')
    explanation_text = get_model_explanation_text(
        recommendation=explanation["recommendation"],
        prediction_percentile=prediction_percentile,
        shap_value_dict=explanation["shap_values"],
        feature_value_dict=explanation["feature_values"],
        model_name=model_name
    )
    explanation["explanation_text"] = explanation_text
    return explanation

def get_model_explanation_text(recommendation: str, prediction_percentile: float, shap_value_dict: dict, feature_value_dict: dict, model_name: str) -> str:
    system_prompt = get_prompt("explain_model")
    user_prompt = _build_user_prompt(
        recommendation=recommendation,
        prediction_percentile=prediction_percentile,
        shap_value_dict=shap_value_dict,
        feature_value_dict=feature_value_dict,
        model_name=model_name
    )
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

def dict_to_text(d: dict) -> str:
    """Convert dict of FeatureValue objects to text"""
    text = ""
    for k, v in d.items():
        # v is now a FeatureValue object (dict with 'value', 'display_name', 'interpretation')
        value = v['value'] if isinstance(v, dict) else v
        text += f"{k}: {value}\n"
    return text

def feature_dict_to_text(d: dict) -> str:
    text = ""
    for k, inner_d in d.items():
        name, interp = inner_d['display_name'], inner_d['interpretation']
        text += f"{k} ({name}): {interp}\n"
    return text
    
def _build_user_prompt(recommendation: str, prediction_percentile: float, shap_value_dict: dict, feature_value_dict: dict, model_name: str) -> str:
    prompt = f"모델 예측 값의 백분위(작을수록 매수를 추천하는 것입니다.): {prediction_percentile}\n"
    prompt += f"추천 매매 의사결정은 다음과 같습니다: {recommendation}\n"
    model_feature_description_dict = get_feature_texts(f'{model_name}_model')
    prompt += f"각 feature의 정의는 아래와 같습니다.\n"
    prompt += feature_dict_to_text(model_feature_description_dict)
    prompt += f"절댓값 상위 SHAP 값은 아래와 같습니다.\n"
    prompt += dict_to_text(shap_value_dict)
    prompt += f"해당 feature 값은 아래와 같습니다.\n"
    prompt += dict_to_text(feature_value_dict)
    return prompt
