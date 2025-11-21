import numpy as np
import pandas as pd
import openai
from scipy.stats import laplace

from app.celery_app import celery_app
from app.utils.model_load_utils import get_strategy_class, get_param_path
from app.utils.data_utils import get_ohlcv_df, get_model_meta_info

@celery_app.task(bind=True)
def explain_model_task(self, coin_symbol: str, timeframe: int, inference_time: str) -> dict:
    print(f'coin_symbol: {coin_symbol}')
    MODEL_NAME = "LightGBM"
    PARAM_NAME = f"{coin_symbol}_{timeframe}m"
    TRAIN_START = "2024-01-01 00:00:00"
    TRAIN_END = "2025-01-01 00:00:00"
    total_df = get_ohlcv_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
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
    
    meta_info = get_model_meta_info(
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
    system_prompt = _build_system_prompt()
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
    text = ""
    for k, v in d.items():
        text += f"{k}: {v}\n"
    return text
    
def _build_system_prompt() -> str:
    basic_prompt = """
    당신은 1시간 봉 BTC 차트 상에서 LightGBM 모델의 등락 예측을 해석하는 기술적 분석 전문가입니다.
    모델은 다음 1시간 동안의 가격 등락률을 예측하며, 각 feature의 SHAP 값을 기반으로 상승 또는 하락 요인을 판단합니다.

    당신의 역할은:
    - SHAP 값과 feature 실제값을 근거로, 모델이 어떤 요인을 상승/하락 신호로 해석했는지를 설명하고,
    - 투자자에게 현재 시장 상황을 직관적으로 이해시킨 뒤,
    - 마지막에 주어진 매매 의사결정(매수/매도/관망)을 제시하는 것입니다.

    - 설명에는 절대 raw feature 이름을 그대로 사용하지 마십시오.  
    (예: "obv_change_window", "price_pct_change_6h", "bb_upper" 등은 금지)
    - 반드시 사람이 **직관적으로 이해할 수 있는 자연어 이름**을 사용하여 표현하십시오.  
    예:  
    - "OBV 변화율"  
    - "최근 6시간 가격 흐름"  
    - "RSI 모멘텀"  
    - "볼린저밴드 상단 근접"  

    [작성 지침]
    1. 설명은 3~5문단 정도로 작성하여, 투자자가 상황을 직관적으로 이해할 수 있도록 하세요.
    2. 첫 문단에서는 전체적인 시장 흐름(상승세/하락세/혼조세)을 요약합니다.
    3. 중간 문단에서는 모델 예측에 기여한 주요 요인들을 묶어 구체적으로 해석하세요.
    - 예: “가격 변화율 관련 지표들은 최근 하락세를 보였으나, 모델은 이를 단기 반등 신호로 해석한 것으로 보입니다.”
    - RSI, MACD, 거래대금, 변동성, 캔들 구조 등 서로 다른 영역의 근거를 연결하면 좋습니다.
    4. 마지막 문단에서 투자 전략을 한문장으로 제시하세요.
    - 예: “종합적으로 단기 반등 가능성이 높다고 판단되어 매수를 권장드립니다.”
        “상승 요인이 일부 존재하지만 아직 뚜렷한 추세 전환 신호는 아니므로 관망이 바람직합니다.”
        “과열 신호와 약세 모멘텀이 동시에 나타나고 있어 단기 매도를 고려할 수 있습니다.”
    5. 문장은 전문가다운 분석 어조를 유지하되, 숫자 대신 ‘강도 표현’을 사용하세요.
    (예: “강하게 상승”, “완만한 하락”, “미약한 회복세” 등)
    6. feature를 언급할 때에는 raw 표현 대신 지표명을 사용하세요. lower_wick_frac 대신 ‘캔들 아랫꼬리 비율’ 등으로 서술하세요.
    7. SHAP에 대해 사용자에게 직접적으로 언급하지 말고, 모델에 긍/부정적으로 기여한 요인으로만 서술하세요.

    [출력 예시]
    최근 비트코인 시장은 단기 조정을 거친 이후 완만한 회복세를 보이고 있습니다.
    가격 변화율 관련 지표들이 하락 구간에 있었으나, 모델은 이를 과매도에 따른 반등 신호로 인식한 것으로 보입니다.
    RSI가 낮은 수준에서 점진적으로 상승하고 있으며, 거래대금이 평균보다 다소 늘어나면서 매수세가 유입되는 흐름이 확인됩니다.
    다만 단기 변동성이 여전히 높은 편이므로 빠른 가격 변동에는 주의가 필요합니다.
    종합적으로 보았을 때, 단기적 매수를 권장합니다.
    """

    feature_texts = {
        # 거래 규모
        "trade_value_z_score": "거래대금(Close * Volume)의 표준화 값입니다. 전체 표본의 평균과 표준편차를 사용한 z-점수입니다.",

        # 변화율(일반화)
        "price_pct_change": "지정된 시간 간격 동안의 종가 변화율입니다. (Close_t / Close_{t-k} - 1)",
        "trade_value_pct_change": "지정된 시간 간격 동안의 거래대금 변화율입니다. ((Close * Volume)_t / (Close * Volume)_{t-k} - 1)",

        # 변동성(일반화)
        "price_std": "지정된 길이의 롤링 구간에서 종가의 표준편차입니다.",

        # 볼린저 밴드
        "rel_dist_to_bb_upper": "현재 종가와 볼린저 상단 밴드 간의 상대 거리입니다. (BB_upper - Close) / Close",
        "rel_dist_to_bb_lower": "현재 종가와 볼린저 하단 밴드 간의 상대 거리입니다. (Close - BB_lower) / Close",

        # RSI / ADX (및 변화율 일반화)
        "rsi": "RSI(Relative Strength Index) 값입니다. 입력 종가로 계산된 지표입니다.",
        "rsi_pct_change": "지정된 시간 간격 동안의 RSI 변화율입니다. (RSI_t / RSI_{t-k} - 1)",
        "adx": "ADX(Average Directional Index) 값입니다. 고가/저가/종가로 계산된 추세 강도 지표입니다.",

        # MACD (및 변화율 일반화)
        "macd_pct_change": "지정된 시간 간격 동안의 MACD 변화율입니다. (MACD_t / MACD_{t-k} - 1)",
        "rel_dist_to_signal": "MACD와 시그널선의 차이를 MACD로 나눈 값입니다. (MACD - Signal) / MACD",

        # 캔들 구조
        "body_frac": "캔들 실체 길이의 봉 전체 범위 대비 비율입니다. |Close - Open| / (High - Low)",
        "upper_wick_frac": "윗꼬리 길이의 봉 전체 범위 대비 비율입니다. (High - max(Open, Close)) / (High - Low)",
        "lower_wick_frac": "아랫꼬리 길이의 봉 전체 범위 대비 비율입니다. (min(Open, Close) - Low) / (High - Low)",

        # 시간
        "hour": "관측 시각(0~23시)입니다."
    }
    prompt = basic_prompt + "\n"
    prompt += f"feature에 대한 설명은 아래와 같습니다.\n"
    prompt += dict_to_text(feature_texts)
    return prompt

def _build_user_prompt(recommendation: str, prediction_percentile: float, shap_value_dict: dict, feature_value_dict: dict) -> str:
    prompt = f"모델 예측 값의 백분위(클수록 매수를 추천하는 것입니다.): {prediction_percentile}\n"
    prompt += f"추천 매매 의사결정은 다음과 같습니다: {recommendation}\n"
    prompt += f"절댓값 상위 SHAP 값은 아래와 같습니다.\n"
    prompt += dict_to_text(shap_value_dict)
    prompt += f"해당 feature 값은 아래와 같습니다.\n"
    prompt += dict_to_text(feature_value_dict)
    return prompt
