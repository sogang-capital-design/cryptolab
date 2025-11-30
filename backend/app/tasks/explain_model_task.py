import numpy as np
import pandas as pd
import openai
from scipy.stats import laplace

from app.celery_app import celery_app
from app.utils.model_load_utils import get_strategy_class, get_param_path
from app.utils.data_utils import get_ohlcv_df, get_model_meta_info, get_onchain_df, get_prompt, get_feature_texts

@celery_app.task(bind=True)
def explain_model_task(self, model_name:str, coin_symbol: str, timeframe: int, inference_time: str) -> dict:
    print(f'[explain_task] model={model_name}, symbol={coin_symbol}, tf={timeframe}')
    MODEL_NAME = model_name
    PARAM_NAME = f"{coin_symbol}_{timeframe}m"
    TRAIN_START = "2024-01-01 00:00:00"
    TRAIN_END = "2025-01-01 00:00:00"
    ohlcv_df = get_ohlcv_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    onchain_df = get_onchain_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    total_df = pd.merge(ohlcv_df, onchain_df, left_index=True, right_index=True, how='inner')
    strategy_class = get_strategy_class(MODEL_NAME)
    inference_window = strategy_class.inference_window
    strategy_instance = strategy_class()

    params_path = get_param_path(MODEL_NAME, PARAM_NAME)
    strategy_instance.load(params_path)

    train_start_timestamp = pd.Timestamp(TRAIN_START).tz_localize(None)
    train_start_timestamp -= pd.Timedelta(minutes=timeframe)
    train_end_timestamp = pd.Timestamp(TRAIN_END).tz_localize(None)
    train_df = total_df.loc[train_start_timestamp:train_end_timestamp]

    inference_timestamp = pd.Timestamp(inference_time).tz_localize(None)
    inference_iloc = total_df.index.get_loc(inference_timestamp)
    inference_df = total_df.iloc[inference_iloc - inference_window:inference_iloc]

    print('Creating SHAP values...')
    explanation = strategy_instance.explain(
        train_df=train_df,
        inference_df=inference_df
    )
    prediction_value = explanation.pop("prediction", 0.0)
    print(f'Prediction value: {prediction_value}')

    # feature 설명 추가
    model_feature_texts = get_feature_texts('model')

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
    # 과대 추정 완화를 위해 std를 1.5배 확대
    mean, std = meta_info["mean"], meta_info["std"] * 1.5
    def prediction_percentile_func(pred: float) -> float:
        percentile = laplace.cdf(pred, loc=mean, scale=std / np.sqrt(2)) * 100
        return percentile
    prediction_percentile = prediction_percentile_func(prediction_value)

    explanation["prediction_percentile"] = prediction_percentile
    if prediction_percentile >= 85:
        explanation["recommendation"] = "Buy"
    elif prediction_percentile >= 70:
        explanation["recommendation"] = "Weak buy"
    elif prediction_percentile >= 30:
        explanation["recommendation"] = "Hold"
    elif prediction_percentile >= 15:
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
    )
    explanation["explanation_text"] = explanation_text
    return explanation

def get_model_explanation_text(recommendation: str, prediction_percentile: float, shap_value_dict: dict, feature_value_dict: dict) -> str:
    system_prompt = get_prompt("explain_model")
    user_prompt = _build_user_prompt(
        recommendation=recommendation,
        prediction_percentile=prediction_percentile,
        shap_value_dict=shap_value_dict,
        feature_value_dict=feature_value_dict
    )
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model='gpt-5.1-chat-latest',
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )
    return response.choices[0].message.content

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
    
def _build_user_prompt(recommendation: str, prediction_percentile: float, shap_value_dict: dict, feature_value_dict: dict) -> str:
    prompt = f"모델 예측 값의 백분위(클수록 매수를 추천하는 것입니다.): {prediction_percentile}\n"
    prompt += f"추천 매매 의사결정은 다음과 같습니다: {recommendation}\n"
    model_feature_description_dict = get_feature_texts('model')
    prompt += f"각 feature의 정의는 아래와 같습니다.\n"
    prompt += feature_dict_to_text(model_feature_description_dict)
    prompt += f"절댓값 상위 SHAP 값은 아래와 같습니다.\n"
    prompt += dict_to_text(shap_value_dict)
    prompt += f"해당 feature 값은 아래와 같습니다.\n"
    prompt += dict_to_text(feature_value_dict)
    return prompt
