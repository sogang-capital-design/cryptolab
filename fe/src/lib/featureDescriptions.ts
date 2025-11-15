// src/lib/featureDescriptions.ts

// 1. 모델 분석(SHAP) 기능의 용어 사전
const MODEL_FEATURES: { [key: string]: { name: string; description: string } } = {
  // --- 정규식(Regex) 키 - "h"가 붙는 그룹 ---
  "price_pct_change_(\\d+)h": {
    "name": "가격 변화율($1시간)",
    "description": "종가의 $1시간 대비 퍼센트 변화율입니다. 양수이면 상승, 음수이면 하락을 의미합니다."
  },
  "trade_value_pct_change_(\\d+)h": {
    "name": "거래가치 변화율($1시간)",
    "description": "거래가치의 $1시간 대비 퍼센트 변화율입니다. 거래량·가격 변화에 따른 시장 참여 강도의 변화를 보여줍니다."
  },
  "rsi_pct_change_(\\d+)h": {
    "name": "RSI 변화율($1시간)",
    "description": "RSI의 $1시간 대비 퍼센트 변화율입니다. RSI가 얼마나 빠르게 상승 또는 하락했는지를 나타냅니다."
  },
  "macd_pct_change_(\\d+)h": {
    "name": "MACD 변화율($1시간)",
    "description": "MACD 값의 $1시간 대비 퍼센트 변화율입니다. 모멘텀의 변화 속도를 보여줍니다."
  },

  // --- 정규식(Regex) 키 - 숫자만 붙는 그룹 ---
  "price_std_(\\d+)": {
    "name": "가격 표준편차($1기간)",
    "description": "해당 기간($1)의 가격 변동성을 나타내는 표준편차입니다. 값이 클수록 가격 변동폭이 큽니다."
  },
  "body_frac_(\\d+)": {
    "name": "몸통 비율($1번째 이전 캔들)",
    "description": "$1번째 이전 캔들의 몸통 길이가 전체 구간(고가-저가)에서 차지하는 비율입니다. 값이 크면 장대양봉 또는 장대음봉일 가능성이 높습니다."
  },
  "upper_wick_frac_(\\d+)": {
    "name": "윗꼬리 비율($1번째 이전 캔들)",
    "description": "$1번째 이전 캔들의 윗꼬리가 전체 구간에서 차지하는 비율입니다. 긴 윗꼬리는 매도 압력을 시사할 수 있습니다."
  },
  "lower_wick_frac_(\\d+)": {
    "name": "아랫꼬리 비율($1번째 이전 캔들)",
    "description": "$1번째 이전 캔들의 아랫꼬리가 전체 구간에서 차지하는 비율입니다. 긴 아랫꼬리는 매수 압력을 시사할 수 있습니다."
  },
  "cur_pct_change_(\\d+)": {
    "name": "현재가 변화율($1번째 이전 캔들)",
    "description": "$1번째 이전 캔들의 시가 대비 종가 변화율입니다. 양수는 상승, 음수는 하락을 의미합니다."
  },
  
  // --- 고정 키 ---
  "trade_value_z_score": {
    "name": "거래가치 Z-Score",
    "description": "거래가치(close × volume)를 전체 구간 기준으로 표준화한 값입니다. 평균 대비 현재 거래강도가 얼마나 높은지 또는 낮은지를 나타냅니다."
  },
  "rel_dist_to_bb_upper": {
    "name": "볼린저밴드 상단 상대거리",
    "description": "현재 가격이 볼린저밴드 상단선에서 얼마나 떨어져 있는지를 비율로 나타낸 값입니다. 값이 낮을수록 상단선(과열 구간)에 더 가까운 상태입니다."
  },
  "rel_dist_to_bb_lower": {
    "name": "볼린저밴드 하단 상대거리",
    "description": "현재 가격이 볼린저밴드 하단선에서 얼마나 떨어져 있는지를 비율로 나타낸 값입니다. 값이 낮을수록 하단선(과매도 구간)에 더 가까운 상태입니다."
  },
  "rsi": {
    "name": "RSI",
    "description": "RSI 지표입니다. 일반적으로 RSI가 높으면 과매수, 낮으면 과매도로 해석됩니다."
  },
  "adx": {
    "name": "ADX",
    "description": "시장 추세의 강도를 나타내는 지표입니다. 값이 높을수록 강한 추세가 반영됩니다."
  },
  "rel_dist_to_signal": {
    "name": "MACD-신호선 상대거리",
    "description": "MACD가 신호선 대비 얼마나 위·아래에 있는지를 비율로 나타낸 값입니다. 양수이면 상승 모멘텀이 우위, 음수이면 하락 모멘텀이 우위로 해석됩니다."
  },
  "hour": {
    "name": "시간 정보",
    "description": "현재 캔들의 시간(0~23)입니다. 시간대별 거래 패턴이나 계절성을 반영할 때 사용됩니다."
  }
};

// 2. 차트 분석(기술적 지표) 기능의 용어 사전
const CHART_FEATURES: { [key: string]: { name: string; description: string } } = {
  "macd_diff": {
    "name": "MACD 히스토그램",
    "description": "MACD와 신호선의 차이를 나타내는 값입니다. 양수이면 상승 모멘텀이 강해지고, 음수이면 하락 모멘텀이 강해지는 경향이 있습니다."
  },
  "rsi": {
    "name": "RSI",
    "description": "가격의 상승과 하락 속도를 기반으로 과매수·과매도 상태를 판단하는 지표입니다. 일반적으로 RSI가 높으면 과매수, 낮으면 과매도로 해석됩니다."
  },
  "bollinger_band_upper": {
    "name": "볼린저밴드 상단선",
    "description": "최근 가격 변동성을 기반으로 계산된 상단선입니다. 가격이 상단선 근처에 있으면 과열 신호로 해석될 수 있습니다."
  },
  "bollinger_band_lower": {
    "name": "볼린저밴드 하단선",
    "description": "최근 가격 변동성을 기반으로 계산된 하단선입니다. 가격이 하단선 근처에 있으면 과매도 신호로 해석될 수 있습니다."
  },
  "bollinger_band_mavg": {
    "name": "볼린저밴드 중심선",
    "description": "볼린저밴드를 구성하는 기준선으로 일반적으로 20일 이동평균선입니다."
  },
  "ema_20": {
    "name": "20기간 지수이동평균",
    "description": "최근 가격에 더 높은 가중치를 두어 계산한 20기간 추세선입니다. 가격이 이 선 위에 있으면 단기 상승 추세로 해석될 수 있습니다."
  },
  "ema_60": {
    "name": "60기간 지수이동평균",
    "description": "최근 가격에 더 높은 가중치를 두어 계산한 60기간 추세선입니다. 가격이 이 선 위에 있으면 중기 상승 추세로 해석될 수 있습니다."
  },
  "adx": {
    "name": "ADX",
    "description": "시장 추세의 강도를 나타내는 지표입니다. 값이 높을수록 강한 추세가 형성되어 있는 것으로 해석됩니다."
  },
  "atr": {
    "name": "ATR",
    "description": "최근 가격 변동폭을 기반으로 시장의 변동성을 나타내는 지표입니다. 값이 높으면 시장의 변동성이 크다는 뜻입니다."
  }
};

// 3. API 키를 한글 이름/설명으로 변환해주는 헬퍼 함수
export const getFeatureInfo = (
  featureKey: string,
  type: "model" | "chart"
): { name: string; description: string } => {
  
  const featureMap = type === "model" ? MODEL_FEATURES : CHART_FEATURES;

  // 1. 정확히 일치하는 키 찾기 (예: "rsi", "adx")
  if (featureMap[featureKey]) {
    return featureMap[featureKey];
  }

  // 2. 동적 키(정규식) 찾기 (예: "price_pct_change_1h")
  if (type === "model") {
    for (const templateKey in featureMap) {
      if (templateKey.includes('(') || templateKey.includes('\\')) {
        const regex = new RegExp(`^${templateKey}$`); 
        const match = featureKey.match(regex);
        
        if (match) {
          const number = match[1]; // "1"
          return {
            name: featureMap[templateKey].name.replace("$1", number), // "가격 변화율(1시간)"
            description: featureMap[templateKey].description.replace("$1", number),
          };
        }
      }
    }
  }

  // 3. 일치하는 것이 없으면 원본 키 반환
  return { name: featureKey, description: "설명 없음" };
};