import numpy as np
import pandas as pd
import ta
import openai
import json

from app.celery_app import celery_app
from app.utils.data_utils import get_total_df_online, get_prompt, get_feature_texts, get_score_meta_info
from app.tasks.explain_chart_task import create_chart_features
from app.utils.cache_utils import cache_task_result

@celery_app.task(bind=True)
@cache_task_result(prefix="score_chart")
def score_chart_task(self, coin_symbol: str, timeframe: int, inference_time: str, history_window: int) -> dict:

    INFERENCE_WINDOW_SIZE = 100
    inference_ts = pd.Timestamp(inference_time)
    if inference_ts.tz is None:
        inference_ts = inference_ts.tz_localize("UTC")
    start_time = inference_ts - pd.Timedelta(hours=INFERENCE_WINDOW_SIZE)
    end_time = inference_ts
    inference_df = get_total_df_online(coin_symbol, start_time, end_time)

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

    score_meta_info = get_score_meta_info()
    for key in chart_score_dict.keys():
        assert key in score_meta_info, f"Score key '{key}' not found in score meta info."
        value = chart_score_dict[key]['score']
        cnt = 0
        for prev_value in score_meta_info[key]:
            if value < prev_value:
                cnt += 1
        percentile = (cnt / len(score_meta_info[key])) * 100
        chart_score_dict[key]['percentile'] = percentile
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
    all_feature_description_dict = get_feature_texts('LightGBM_model')
    user_prompt += feature_dict_to_text(all_feature_description_dict)
    return user_prompt