import numpy as np
import pandas as pd
import ta
import openai
import json

from app.celery_app import celery_app
from app.utils.data_utils import get_ohlcv_df, get_onchain_df, get_prompt, get_feature_texts
from app.tasks.explain_chart_task import create_chart_features

@celery_app.task(bind=True)
def score_chart_task(self, coin_symbol: str, timeframe: int, inference_time: str, history_window: int) -> dict:
    ohlcv_df = get_ohlcv_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    onchain_df = get_onchain_df(
        coin_symbol=coin_symbol,
        timeframe=timeframe
    )
    total_df = pd.merge(ohlcv_df, onchain_df, left_index=True, right_index=True, how='inner')
    inference_timestamp = pd.Timestamp(inference_time).tz_localize(None)
    inference_iloc = total_df.index.get_loc(inference_timestamp)
    inference_df = total_df.iloc[inference_iloc - history_window + 1:inference_iloc + 1]
    system_prompt = get_prompt("score_chart")
    chart_features = create_chart_features(inference_df)
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

def _build_user_prompt(chart_features: dict) -> str:
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
    user_prompt = "다음은 암호화폐 차트의 기술적 지표(feature) 값들과 각 지표의 정의입니다.\n"
    user_prompt += "이를 바탕으로 시장 상황을 해석하고 5가지 점수를 설명과 함께 산출해 주세요.\n\n"
    user_prompt += dict_to_text(chart_features)
    user_prompt += "\n[Feature Definitions]\n"
    all_feature_description_dict = get_feature_texts('chart')
    user_prompt += feature_dict_to_text(all_feature_description_dict)
    return user_prompt