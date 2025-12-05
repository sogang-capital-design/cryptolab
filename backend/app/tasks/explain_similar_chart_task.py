import numpy as np
import pandas as pd
import openai
from dtaidistance import dtw

from app.celery_app import celery_app
from app.utils.data_utils import get_feature_texts, get_total_df, get_total_df_online, get_prompt
from app.utils.cache_utils import cache_task_result

@celery_app.task(bind=True)
@cache_task_result(prefix="explain_similar_chart")
def explain_similar_chart_task(self, coin_symbol: str, timeframe: int, inference_time: str, search_start: str, search_end: str) -> dict:
    total_df = get_total_df(coin_symbol)

    WINDOW_SIZE = 12
    INFERENCE_WINDOW_SIZE = 100
    inference_ts = pd.Timestamp(inference_time)
    if inference_ts.tz is None:
        inference_ts = inference_ts.tz_localize("UTC")
    start_time = inference_ts - pd.Timedelta(hours=INFERENCE_WINDOW_SIZE)
    end_time = inference_ts
    inference_df = get_total_df_online(coin_symbol, start_time, end_time)
    inference_df = inference_df.iloc[-WINDOW_SIZE:]

    explanation = {}
    print('Finding similar charts...')
    start_timestamp = pd.Timestamp(search_start)
    if start_timestamp.tz is None:
        start_timestamp = start_timestamp.tz_localize("UTC")
    end_timestamp = pd.Timestamp(search_end)
    if end_timestamp.tz is None:
        end_timestamp = end_timestamp.tz_localize("UTC")
    chart_df = total_df.loc[start_timestamp:end_timestamp]
    # 인퍼런스 시점이 포함된 구간은 유사도 계산 대상에서 제외
    inference_start = inference_df.index[0]
    inference_end = inference_df.index[-1]
    chart_df = chart_df.loc[(chart_df.index < inference_start) | (chart_df.index > inference_end)]
    similar_charts = get_similar_charts(
        chart_df=chart_df,
        inference_df=inference_df,
        top_k=100,
        window_size=WINDOW_SIZE
    )
    top_similar_charts = similar_charts[:4]
    explanation["top_similar_charts"] = top_similar_charts
    stats = get_similar_chart_stats(similar_charts, chart_df, window_size=WINDOW_SIZE)

    # 전체 feature_stats로 설명 생성
    full_feature_stats = stats["feature_stats"]

    # pct_diff 기준 상위 10개 선택 (LLM 입력 제한)
    sorted_features = sorted(
        full_feature_stats.items(),
        key=lambda x: abs(x[1]['pct_diff']),
        reverse=True
    )
    top_features = dict(sorted_features[:10])

    explanation_text = get_similar_chart_explanation_text(top_features)

    # LLM을 사용하여 중요 지표 추출 (상위 10개 중에서 최대 6개)
    print('Extracting key features...')
    key_feature_names = extract_key_features(explanation_text, top_features, max_features=6)

    # 중요 지표만 필터링 (최대 6개)
    key_feature_stats = {k: v for k, v in top_features.items() if k in key_feature_names}

    # 만약 LLM이 6개보다 많이 선택했다면 pct_diff 기준으로 상위 6개만
    if len(key_feature_stats) > 6:
        sorted_key_features = sorted(
            key_feature_stats.items(),
            key=lambda x: abs(x[1]['pct_diff']),
            reverse=True
        )
        key_feature_stats = dict(sorted_key_features[:6])

    # feature 설명 추가
    chart_feature_texts = get_feature_texts('LightGBM_model')
    for feature_name in key_feature_stats:
        if feature_name in chart_feature_texts:
            feature_info = chart_feature_texts[feature_name]
            key_feature_stats[feature_name]['display_name'] = feature_info['display_name']
            key_feature_stats[feature_name]['interpretation'] = feature_info['interpretation']
        else:
            # pct_change feature의 경우 동적으로 설명 생성
            if '_pct_change_' in feature_name:
                parts = feature_name.rsplit('_pct_change_', 1)
                base_feature = parts[0]
                timeframe = parts[1].replace('h', '')

                if base_feature in chart_feature_texts:
                    base_info = chart_feature_texts[base_feature]
                    key_feature_stats[feature_name]['display_name'] = f"{base_info['display_name']} ({timeframe}시간 변화율)"
                    key_feature_stats[feature_name]['interpretation'] = f"{timeframe}시간 전 대비 {base_info['display_name']}의 변화율입니다. {base_info['interpretation']}"
                else:
                    key_feature_stats[feature_name]['display_name'] = f"{base_feature} ({timeframe}시간 변화율)"
                    key_feature_stats[feature_name]['interpretation'] = f"{timeframe}시간 전 대비 변화율"

    # 최종 결과에는 중요 지표만 포함
    stats["feature_stats"] = key_feature_stats
    explanation["similar_chart_stats"] = stats
    explanation["explanation_text"] = explanation_text
    print(f"Total features: {len(full_feature_stats)}, Top 15: {len(top_features)}, Key features: {len(key_feature_stats)}")
    print(f"Key feature names: {list(key_feature_stats.keys())}")
    return explanation

def get_similar_charts(chart_df: pd.DataFrame, inference_df: pd.DataFrame, top_k: int, window_size: int) -> list[dict]:
    arr = np.asarray(chart_df['close'])
    inputs = np.lib.stride_tricks.sliding_window_view(arr, window_size, axis=0)
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
        dist = dtw.distance_fast(inference_data, cur_data, window=1)
        dists.append(dist)
    dists = np.array(dists)

    MIN_GAP = window_size
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
        end_idx = topk_indices[i] + window_size - 1
        timestamp = chart_df.index[end_idx]
        distance = topk_distances[i]
        results.append({
            "timestamp": timestamp,
            "distance": distance
        })
    return results

def get_similar_chart_stats(similar_charts: list[dict], chart_df: pd.DataFrame, window_size: int) -> dict:

    price_up_features_list = []
    price_down_features_list = []

    for sim_chart in similar_charts:
        timestamp = sim_chart["timestamp"]
        future_timestamp = timestamp + pd.Timedelta(hours=3)

        # 3시간 후 데이터가 존재하는지 확인
        if future_timestamp not in chart_df.index:
            continue

        price_change_3h = chart_df['close'].loc[future_timestamp] / chart_df['close'].loc[timestamp] - 1.0
        # mean을 사용하여 계산
        mean_features = chart_df.loc[timestamp - pd.Timedelta(hours=window_size):timestamp - pd.Timedelta(hours=1)].mean()

        if price_change_3h > 0:
            price_up_features_list.append(mean_features)
        else:
            price_down_features_list.append(mean_features)

    price_up_count = len(price_up_features_list)
    price_down_count = len(price_down_features_list)

    # Zero division 방지
    if price_up_count == 0 or price_down_count == 0:
        return {
            "price_up_count": price_up_count,
            "price_down_count": price_down_count,
            "feature_stats": {}
        }

    # DataFrame으로 변환 후 mean 계산
    price_up_df = pd.DataFrame(price_up_features_list)
    price_down_df = pd.DataFrame(price_down_features_list)

    price_up_feature_means = price_up_df.mean().to_dict()
    price_down_feature_means = price_down_df.mean().to_dict()

    feature_stats = {}
    for k in price_up_feature_means.keys():
        up_val = price_up_feature_means[k]
        down_val = price_down_feature_means[k]

        # NaN이나 inf 체크
        if np.isnan(up_val) or np.isnan(down_val) or np.isinf(up_val) or np.isinf(down_val):
            continue

        feature_stats[k] = {
            'up_value': up_val,
            'down_value': down_val,
            'diff': up_val - down_val,
            'pct_diff': (up_val - down_val) / (abs(down_val) + 1e-12)
        }

    return {
        "price_up_count": price_up_count,
        "price_down_count": price_down_count,
        "feature_stats": feature_stats
    }

def stat_dict_to_text(stat_dict: dict) -> str:
    text = ""
    for feature_name, stats in stat_dict.items():
        text += (f"{feature_name} - "
                 f"Up Mean: {stats['up_value']:.6f}, "
                 f"Down Mean: {stats['down_value']:.6f}, "
                 f"Diff: {stats['diff']:.6f}, "
                 f"Pct Diff: {stats['pct_diff']*100:.2f}%\n")
    return text

def feature_dict_to_text(d: dict) -> str:
    text = ""
    for k, inner_d in d.items():
        name, interp = inner_d['display_name'], inner_d['interpretation']
        text += f"{k} ({name}): {interp}\n"
    return text

def get_similar_chart_explanation_text(similar_chart_stats: dict) -> str:
    system_prompt = get_prompt("explain_similar_chart")

    # 통계 요약 정보
    user_prompt = "현재 차트 패턴과 유사한 과거 구간들의 통계를 분석해 주십시오.\n\n"
    user_prompt += "=== 유사 구간 통계 ===\n"
    user_prompt += stat_dict_to_text(similar_chart_stats)

    # feature 해석 가이드 추가
    chart_feature_description_dict = get_feature_texts('LightGBM_model')
    filtered_chart_feature_description_dict = {k: v for k, v in chart_feature_description_dict.items() if k in similar_chart_stats}
    user_prompt += "\n=== 각 지표의 의미 ===\n"
    user_prompt += feature_dict_to_text(filtered_chart_feature_description_dict)

    user_prompt += "\n위 통계를 바탕으로, 과거 유사 패턴에서 상승 케이스와 하락 케이스의 특징을 분석하고, 투자자가 이해하기 쉬운 자연스러운 문단 형식으로 설명해 주십시오."

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model='gpt-5.1-chat-latest',
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )
    return response.choices[0].message.content

def extract_key_features(explanation_text: str, feature_stats: dict, max_features: int = 6) -> list[str]:
    """LLM을 사용하여 explanation에서 실제로 언급된 중요 지표들을 추출"""
    system_prompt = f"""당신은 암호화폐 분석 텍스트에서 언급된 지표들을 추출하는 전문가입니다.
주어진 분석 텍스트를 읽고, 실제로 언급되고 중요하게 다뤄진 feature 이름들을 추출하십시오.

출력 형식: JSON 객체 형태로 반환
{{
  "features": ["feature_name1", "feature_name2", ...]
}}

주의사항:
- 텍스트에서 실제로 의미있게 언급된 지표만 포함
- **정확히 {max_features}개만 선택** (최소 {max_features}개, 최대 {max_features}개)
- 중요도 순서로 정렬
- 반드시 "features" 키를 사용하여 배열 반환"""

    feature_list = "\n".join([f"- {k}" for k in feature_stats.keys()])
    user_prompt = f"""분석 텍스트:
{explanation_text}

사용 가능한 feature 목록:
{feature_list}

위 분석 텍스트에서 실제로 언급되고 중요하게 다뤄진 feature들을 **정확히 {max_features}개만** 추출하여 JSON 형식으로 반환해 주십시오.
형식: {{"features": ["feature1", "feature2", "feature3", "feature4", "feature5", "feature6"]}}"""

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model='gpt-5.1-chat-latest',
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
    )

    import json
    result = json.loads(response.choices[0].message.content)
    print(f"LLM response: {result}")

    # JSON 응답에서 features 추출
    if isinstance(result, dict):
        features = result.get("features", result.get("key_features", []))
        if not features:
            # 만약 비어있다면, pct_diff 상위 6개 반환
            print(f"Warning: LLM returned empty features, using top {max_features} by pct_diff")
            sorted_by_pct = sorted(feature_stats.items(), key=lambda x: abs(x[1]['pct_diff']), reverse=True)
            return [k for k, v in sorted_by_pct[:max_features]]

        # max_features로 제한
        return features[:max_features]

    # 예상치 못한 형식이면 pct_diff 상위 6개 반환
    print(f"Warning: Unexpected response format, using top {max_features} by pct_diff")
    sorted_by_pct = sorted(feature_stats.items(), key=lambda x: abs(x[1]['pct_diff']), reverse=True)
    return [k for k, v in sorted_by_pct[:max_features]]