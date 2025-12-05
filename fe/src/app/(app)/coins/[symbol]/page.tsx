// app/(app)/coins/[symbol]/page.tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { fetchWithAuth } from "../../layout";
// 1. '설명 없음' 문제를 해결한 헬퍼 함수 임포트
import { getFeatureInfo } from "@/lib/featureDescriptions";
// 2. 업비트 과거 캔들 차트 컴포넌트 임포트
import HistoricalCandleChart from "@/components/HistoricalCandleChart";

// --- 추가 타입 정의 ---
interface CoinListResponse {
  available_coin_symbols: string[];
}

interface WatchlistResponse {
  coin_symbols: string[];
}

// --- 타입 정의 ---
interface FeatureValue {
  value: number;
  display_name?: string;
  interpretation?: string;
}

interface ExplainModelResult {
  prediction_percentile: number;
  recommendation: "Buy" | "Weak buy" | "Hold" | "Weak sell" | "Sell";
  shap_values: { [feature: string]: FeatureValue };
  feature_values: { [feature: string]: FeatureValue };
  reference_charts: { timestamp: string; similarity: number }[];
  explanation_text: string;
}

interface ExplainChartResult {
  feature_values: { [feature: string]: FeatureValue };
  explanation_text: string;
}

interface DifferenceStats {
  up_value: number;
  down_value: number;
  diff: number;
  pct_diff: number;
  display_name?: string;
  interpretation?: string;
}

interface SimilarChartStats {
  price_up_count: number;
  price_down_count: number;
  feature_stats: { [feature: string]: DifferenceStats };
}

interface ExplainSimilarChartResult {
  top_similar_charts: { timestamp: string; distance: number }[];
  similar_chart_stats: SimilarChartStats;
  explanation_text: string;
}

interface ScoreWithExplanation {
  score: number;
  percentile: number;
  explanation: string;
}
type ScoreMetricKey =
  | "volatility_risk"
  | "overextension"
  | "directionality"
  | "breakout_strength"
  | "accumulation_distribution";

type ScoreChartResults = Record<ScoreMetricKey, ScoreWithExplanation>;

interface ScoreChartApiTaskResponse {
  task_id: string;
  status: string;
  results?: ScoreChartResults | null;
}

const SCORE_TIMEFRAME = 60;
const SCORE_HISTORY_WINDOW = 120;

const SCORE_METRIC_META: Array<{
  key: ScoreMetricKey;
  label: string;
  rangeHint: string;
  description: string;
  min: number;
  max: number;
}> = [
  {
    key: "volatility_risk",
    label: "변동성 위험",
    rangeHint: "0~100",
    description:
      "현재 가격 움직임이 일관되지 않고 크게 흔들릴수록 높아지는 위험 지표입니다.",
    min: 0,
    max: 100,
  },
  {
    key: "overextension",
    label: "과열/과매도",
    rangeHint: "-100~100",
    description:
      "과열(과도한 상승) 또는 과매도(과도한 하락)에 가까운 정도를 나타내며, 0에 가까울수록 균형입니다.",
    min: -100,
    max: 100,
  },
  {
    key: "directionality",
    label: "추세 방향성",
    rangeHint: "-100~100",
    description:
      "현재 시장이 상승 우위인지 하락 우위인지, 얼마나 방향성이 뚜렷한지를 보여줍니다.",
    min: -100,
    max: 100,
  },
  {
    key: "breakout_strength",
    label: "돌파 강도",
    rangeHint: "0~100",
    description:
      "가격이 이전 레인지에서 벗어나고자 하는 힘이며, 값이 높을수록 돌파 가능성이 커집니다.",
    min: 0,
    max: 100,
  },
  {
    key: "accumulation_distribution",
    label: "분산/매집",
    rangeHint: "-100~100",
    description:
      "누적 거래량 흐름과 꼬리 거래량 비중을 계산하여, 단순한 매수/매도보다 기관급 대량 흐름의 방향성을 파악합니다.",
    min: -100,
    max: 100,
  },
];

const interpolateScoreColor = (value: number, min: number, max: number) => {
  if (!Number.isFinite(value)) return "text-white";
  const clamped = Math.max(min, Math.min(max, value));
  const ratio = (clamped - min) / (max - min || 1);
  if (ratio <= 0.15) return "text-rose-400";
  if (ratio <= 0.3) return "text-rose-300";
  if (ratio <= 0.45) return "text-orange-300";
  if (ratio <= 0.55) return "text-white";
  if (ratio <= 0.7) return "text-lime-200";
  if (ratio <= 0.85) return "text-lime-300";
  return "text-emerald-300";
};

const getScoreValueClassName = (
  value: number,
  metricKey: ScoreMetricKey
) => {
  const metric = SCORE_METRIC_META.find((item) => item.key === metricKey);
  if (!metric) return "text-white";
  return interpolateScoreColor(value, metric.min, metric.max);
};

interface ApiTaskResponse {
  task_id: string;
  status: string;
  results?: ExplainModelResult | ExplainChartResult | null;
}

interface CoinInfoResponse {
  available_start: string;
  available_end: string;
}

const formatDateTimeLocal = (date: Date) => {
  if (!date || isNaN(date.getTime())) {
    // 유효하지 않은 날짜인 경우 현재 시간 사용
    date = new Date();
  }
  const tzOffsetMs = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - tzOffsetMs).toISOString().slice(0, 16);
};

const toHourPrecision = (timestamp: string) => {
  if (!timestamp.includes("T")) {
    return timestamp;
  }
  const [date, time] = timestamp.split("T");
  const hour = time.slice(0, 2);
  return `${date}T${hour}:00`;
};

const convertKstToUtc = (kstTimestamp: string) => {
  // KST (UTC+9)를 UTC로 변환
  // kstTimestamp 형식: "2024-01-01T12:00"
  if (!kstTimestamp.includes("T")) {
    return kstTimestamp;
  }

  // datetime-local 값을 KST로 해석하고 UTC로 변환
  const date = new Date(kstTimestamp);
  // 9시간을 빼서 UTC로 변환
  const utcDate = new Date(date.getTime() - 9 * 60 * 60 * 1000);

  // "YYYY-MM-DD HH:mm:ss" 형식으로 반환
  const year = utcDate.getFullYear();
  const month = String(utcDate.getMonth() + 1).padStart(2, '0');
  const day = String(utcDate.getDate()).padStart(2, '0');
  const hour = String(utcDate.getHours()).padStart(2, '0');
  const minute = String(utcDate.getMinutes()).padStart(2, '0');

  return `${year}-${month}-${day} ${hour}:${minute}:00`;
};

const recommendationLabelMap: Record<ExplainModelResult["recommendation"], string> = {
  Buy: "상승 신호",
  "Weak buy": "약한 상승 신호",
  Hold: "혼조 구간",
  "Weak sell": "약한 하락 신호",
  Sell: "하락 신호",
};

const getRecommendationLabel = (recommendation: ExplainModelResult["recommendation"]) =>
  recommendationLabelMap[recommendation] ?? recommendation;

const renderBoldText = (text: string) => {
  const segments = text.split("**");
  return segments.map((segment, idx) =>
    idx % 2 === 1 ? (
      <strong key={segment + idx} className="font-semibold text-white">
        {segment}
      </strong>
    ) : (
      <span key={segment + idx}>{segment}</span>
    )
  );
};

const getDirectionalColorClass = (value: number) => {
  if (!Number.isFinite(value) || Math.abs(value) <= 5) return "text-white";
  if (value > 0) {
    if (value >= 20) return "text-sky-300";
    if (value >= 5) return "text-sky-200";
  } else {
    if (value <= -20) return "text-rose-300";
    if (value <= -5) return "text-rose-200";
  }
  return "text-white";
};

const getModelPercentileColor = (percentile: number) => {
  if (!Number.isFinite(percentile)) return "text-white";
  const diff = percentile - 50;
  return getDirectionalColorClass(diff);
};


// --- 헬퍼 컴포넌트: SHAP 차트 (툴팁 적용) ---
function ShapChart({ shapValues }: { shapValues: { [key: string]: FeatureValue } }) {
  const sortedShap = Object.entries(shapValues).sort(([, a], [, b]) => Math.abs(b.value) - Math.abs(a.value));
  const maxVal = Math.max(...sortedShap.map(entry => Math.abs(entry[1].value)), 1e-9);

  return (
    <div className="space-y-2">
      <h3 className="text-xl font-semibold mb-3">AI 추천 핵심 근거 (SHAP)</h3>
      {sortedShap.map(([featureKey, valueObj]) => {
        const value = valueObj.value;
        // Use backend-provided descriptions with fallback
        const displayName = valueObj.display_name || getFeatureInfo(featureKey, "model").name;
        const interpretation = valueObj.interpretation || getFeatureInfo(featureKey, "model").description;
        const isPositive = value > 0;
        const widthPercent = (Math.abs(value) / maxVal) * 100;

        return (
          <div key={featureKey} className="w-full">
            <div className="flex justify-between text-xs text-gray-300 mb-1">
              {/* title 속성으로 툴팁 추가 */}
              <span
                className="cursor-help"
                title={interpretation} // 마우스를 올리면 설명이 툴팁으로 뜸
              >
                {displayName} {/* 한글 이름 표시 */}
              </span>
              <span className={isPositive ? "text-green-400" : "text-red-400"}>
                {value.toFixed(6)}
              </span>
            </div>
            <div className="h-4 bg-gray-700 rounded overflow-hidden">
              <div
                className={isPositive ? "bg-green-500" : "bg-red-500"}
                style={{ width: `${widthPercent}%`, height: "100%" }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// --- 메인 컴포넌트 ---
export default function CoinDetailPage() {
  const params = useParams();
  const router = useRouter();
  const coinSymbol = Array.isArray(params.symbol) ? params.symbol[0] : params.symbol;

  // Transformer 모델을 지원하는 코인 목록
  const TRANSFORMER_SUPPORTED_COINS = ["ETH", "LINK", "PEPE", "SHIB", "UNI"];
  const supportsTransformer = coinSymbol ? TRANSFORMER_SUPPORTED_COINS.includes(coinSymbol) : false;

  // 0. 코인 목록 및 관심 코인 상태
  const [availableCoins, setAvailableCoins] = useState<string[]>([]);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [showCoinSelector, setShowCoinSelector] = useState(false);

  // 1. 데이터 상태
  const [coinInfo, setCoinInfo] = useState<CoinInfoResponse | null>(null);
  const [selectedTimestamp, setSelectedTimestamp] = useState<string>(() =>
    toHourPrecision(formatDateTimeLocal(new Date()))
  );

  // 2. '모델 분석' 상태 (LightGBM)
  const [modelTask, setModelTask] = useState<ApiTaskResponse | null>(null);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  // 2-1. 'Transformer 모델 분석' 상태
  const [transformerTask, setTransformerTask] = useState<ApiTaskResponse | null>(null);
  const [transformerLoading, setTransformerLoading] = useState(false);
  const [transformerError, setTransformerError] = useState<string | null>(null);

  // 3. '차트 분석' 상태
  const [chartTask, setChartTask] = useState<ApiTaskResponse | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"lightgbm" | "transformer" | "chart">("lightgbm");
  const [scoreTask, setScoreTask] = useState<ScoreChartApiTaskResponse | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [scoreError, setScoreError] = useState<string | null>(null);
  const scoreResults = scoreTask?.results ?? null;
  const scorePollingRef = useRef<NodeJS.Timeout | null>(null);
  const [chartSection, setChartSection] = useState<
    "indicators" | "similar" | "scores"
  >("indicators");

  // 4. '유사 차트 분석' 상태
  const [similarTask, setSimilarTask] = useState<ApiTaskResponse | null>(null);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [similarError, setSimilarError] = useState<string | null>(null);
  const similarPollingRef = useRef<NodeJS.Timeout | null>(null);

  // --- Transformer를 지원하지 않는 코인으로 이동 시 탭을 lightgbm으로 변경 ---
  useEffect(() => {
    if (!supportsTransformer && activeTab === "transformer") {
      setActiveTab("lightgbm");
    }
  }, [supportsTransformer, activeTab]);

  // --- 코인 목록 및 관심 코인 로드 ---
  useEffect(() => {
    const fetchCoinsAndWatchlist = async () => {
      try {
        // 코인 목록 가져오기
        const coinsRes = await fetch("http://localhost:8000/data/list");
        if (coinsRes.ok) {
          const data: CoinListResponse = await coinsRes.json();
          setAvailableCoins(data.available_coin_symbols);
        }

        // 관심 코인 가져오기 (로그인 상태일 때만)
        const token = localStorage.getItem("access_token");
        if (token) {
          const watchlistRes = await fetchWithAuth("http://localhost:8000/watchlist");
          if (watchlistRes.ok) {
            const data: WatchlistResponse = await watchlistRes.json();
            setWatchlist(data.coin_symbols);
          }
        }
      } catch (error) {
        console.error("코인 목록 또는 관심 코인 로드 실패:", error);
      }
    };

    fetchCoinsAndWatchlist();
  }, []);

  // --- 관심 코인 토글 ---
  const handleToggleWatchlist = async (coin: string) => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      alert("로그인이 필요합니다.");
      return;
    }

    try {
      const isInWatchlist = watchlist.includes(coin);
      const endpoint = isInWatchlist
        ? "http://localhost:8000/watchlist/remove"
        : "http://localhost:8000/watchlist/add";
      const method = isInWatchlist ? "DELETE" : "POST";

      const res = await fetchWithAuth(endpoint, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ coin_symbol: coin }),
      });

      if (res.ok) {
        const data: WatchlistResponse = await res.json();
        setWatchlist(data.coin_symbols);
      } else {
        const errorData = await res.json();
        alert(`관심 코인 ${isInWatchlist ? "제거" : "추가"} 실패: ${errorData.detail || "알 수 없는 오류"}`);
      }
    } catch (error) {
      console.error("관심 코인 토글 실패:", error);
      alert("관심 코인 처리 중 오류가 발생했습니다.");
    }
  };

  // --- 데이터 Fetch (코인 분석 가능 기간) ---
  useEffect(() => {
    // coinSymbol이 유효할 때만 API 호출
    if (!coinSymbol) return;

    const fetchCoinInfo = async () => {
      try {
        const res = await fetch("http://localhost:8000/data/info", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ coin_symbol: coinSymbol }),
        });
        const data: CoinInfoResponse = await res.json();
        console.log("[coinInfo] 받은 데이터:", data);
        setCoinInfo(data);

        // 기본값을 현재 시점으로 설정 (inference는 현재 시점까지 가능)
        const now = new Date();
        const defaultLocal = toHourPrecision(formatDateTimeLocal(now));

        setSelectedTimestamp((prev) => {
          // 이미 선택된 timestamp가 있으면 유지
          if (prev) {
            return toHourPrecision(prev);
          }
          // 처음 로드 시 현재 시점으로 설정
          return defaultLocal;
        });
      } catch (e) {
        console.error("코인 정보 로드 실패", e);
      }
    };
    fetchCoinInfo();
  }, [coinSymbol]); // coinSymbol이 확정되면 실행

  // --- 모델 분석 폴링 ---
  useEffect(() => {
    if (!modelTask?.task_id) {
      return;
    }

    const isPending =
      modelTask.status === "PENDING" || modelTask.status === "STARTED";

    if (!isPending) {
      setModelLoading(false);
      return;
    }

    const taskId = modelTask.task_id;
    console.log(`[model] 폴링 시작... Task ID: ${taskId}`);

    const pollModelStatus = async () => {
      try {
        console.log(`[model] 작업 상태 확인 중... (ID: ${taskId})`);

        const res = await fetchWithAuth(
          `http://localhost:8000/explain/model/${taskId}`
        );
        const data = (await res.json()) as ApiTaskResponse;
        if (!res.ok) {
          throw new Error("모델 분석 상태 조회에 실패했습니다.");
        }

        console.log(`[model] 현재 상태:`, data.status);
        setModelTask(data);

        if (data.status === "FAILURE") {
          setModelError("AI 분석에 실패했습니다. (백엔드 에러)");
        }
        if (data.status === "SUCCESS") {
          setModelError(null);
        }
        if (data.status !== "PENDING" && data.status !== "STARTED") {
          setModelLoading(false);
        }
      } catch (err: unknown) {
        setModelLoading(false);
        setModelError(err instanceof Error ? err.message : "Unknown error");
        console.error("[model] 폴링 중 에러:", err);
      }
    };

    pollModelStatus();
    const intervalId = setInterval(pollModelStatus, 3000);

    return () => {
      clearInterval(intervalId);
    };
  }, [modelTask?.task_id, modelTask?.status]);

  // --- Transformer 모델 분석 폴링 ---
  useEffect(() => {
    if (!transformerTask?.task_id) {
      return;
    }

    const isPending =
      transformerTask.status === "PENDING" || transformerTask.status === "STARTED";

    if (!isPending) {
      setTransformerLoading(false);
      return;
    }

    const taskId = transformerTask.task_id;
    console.log(`[transformer] 폴링 시작... Task ID: ${taskId}`);

    const pollTransformerStatus = async () => {
      try {
        console.log(`[transformer] 작업 상태 확인 중... (ID: ${taskId})`);

        const res = await fetchWithAuth(
          `http://localhost:8000/explain/model/${taskId}`
        );
        const data = (await res.json()) as ApiTaskResponse;
        if (!res.ok) {
          throw new Error("Transformer 모델 분석 상태 조회에 실패했습니다.");
        }

        console.log(`[transformer] 현재 상태:`, data.status);
        setTransformerTask(data);

        if (data.status === "FAILURE") {
          setTransformerError("Transformer AI 분석에 실패했습니다. (백엔드 에러)");
        }
        if (data.status === "SUCCESS") {
          setTransformerError(null);
        }
        if (data.status !== "PENDING" && data.status !== "STARTED") {
          setTransformerLoading(false);
        }
      } catch (err: unknown) {
        setTransformerLoading(false);
        setTransformerError(err instanceof Error ? err.message : "Unknown error");
        console.error("[transformer] 폴링 중 에러:", err);
      }
    };

    pollTransformerStatus();
    const intervalId = setInterval(pollTransformerStatus, 3000);

    return () => {
      clearInterval(intervalId);
    };
  }, [transformerTask?.task_id, transformerTask?.status]);

  useEffect(() => {
    if (!scoreTask?.task_id) {
      return;
    }

    const isPending =
      scoreTask.status === "PENDING" || scoreTask.status === "STARTED";

    if (!isPending) {
      setScoreLoading(false);
      if (scorePollingRef.current) {
        clearInterval(scorePollingRef.current);
        scorePollingRef.current = null;
      }
      return;
    }

    const taskId = scoreTask.task_id;

    const pollScoreStatus = async () => {
      try {
        const response = await fetchWithAuth(
          `http://localhost:8000/score-chart/${taskId}`
        );
        const data = (await response.json()) as ScoreChartApiTaskResponse;
        if (!response.ok) {
          throw new Error("차트 점수 상태 조회에 실패했습니다.");
        }
        setScoreTask(data);
        if (data.status === "FAILURE") {
          setScoreError("차트 점수 계산에 실패했습니다.");
        }
        if (data.status === "SUCCESS") {
          setScoreError(null);
        }
        if (data.status !== "PENDING" && data.status !== "STARTED") {
          setScoreLoading(false);
        }
      } catch (err: unknown) {
        if (scorePollingRef.current) {
          clearInterval(scorePollingRef.current);
          scorePollingRef.current = null;
        }
        setScoreLoading(false);
        setScoreError(err instanceof Error ? err.message : "Unknown error");
        console.error("[score] 폴링 중 에러:", err);
      }
    };

    pollScoreStatus();
    scorePollingRef.current = setInterval(pollScoreStatus, 3000);

    return () => {
      if (scorePollingRef.current) {
        clearInterval(scorePollingRef.current);
        scorePollingRef.current = null;
      }
    };
  }, [scoreTask?.task_id, scoreTask?.status]);

  // --- 차트 폴링 ---
  useEffect(() => {
    if (!chartTask?.task_id) {
      return;
    }

    const isPending =
      chartTask.status === "PENDING" || chartTask.status === "STARTED";

    if (!isPending) {
      setChartLoading(false);
      return;
    }

    const taskId = chartTask.task_id;
    console.log(`[chart] 폴링 시작... Task ID: ${taskId}`);

    const pollChartStatus = async () => {
      try {
        console.log(`[chart] 작업 상태 확인 중... (ID: ${taskId})`);

        const response = await fetchWithAuth(
          `http://localhost:8000/explain/chart/${taskId}`
        );
        const data = (await response.json()) as ApiTaskResponse;
        if (!response.ok) {
          throw new Error("차트 분석 상태 조회에 실패했습니다.");
        }

        console.log(`[chart] 현재 상태:`, data.status);
        setChartTask(data);

        if (data.status === "FAILURE") {
          setChartError("차트 분석에 실패했습니다.");
        }
        if (data.status === "SUCCESS") {
          setChartError(null);
          console.log("[chart] Results:", data.results);
        }
        if (data.status !== "PENDING" && data.status !== "STARTED") {
          setChartLoading(false);
        }
      } catch (err: unknown) {
        setChartLoading(false);
        setChartError(err instanceof Error ? err.message : "Unknown error");
        console.error("[chart] 폴링 중 에러:", err);
      }
    };

    pollChartStatus();
    const intervalId = setInterval(pollChartStatus, 3000);

    return () => {
      clearInterval(intervalId);
    };
  }, [chartTask?.task_id, chartTask?.status]);

  // --- 유사 차트 폴링 ---
  useEffect(() => {
    if (!similarTask?.task_id) {
      return;
    }

    const isPending =
      similarTask.status === "PENDING" || similarTask.status === "STARTED";

    if (!isPending) {
      setSimilarLoading(false);
      if (similarPollingRef.current) {
        clearInterval(similarPollingRef.current);
        similarPollingRef.current = null;
      }
      return;
    }

    const taskId = similarTask.task_id;

    const pollSimilarStatus = async () => {
      try {
        const response = await fetchWithAuth(
          `http://localhost:8000/explain/similar_chart/${taskId}`
        );
        const data = (await response.json()) as ApiTaskResponse;
        if (!response.ok) {
          throw new Error("유사 차트 상태 조회에 실패했습니다.");
        }
        setSimilarTask(data);
        if (data.status === "FAILURE") {
          setSimilarError("유사 차트 분석에 실패했습니다.");
        }
        if (data.status === "SUCCESS") {
          setSimilarError(null);
        }
        if (data.status !== "PENDING" && data.status !== "STARTED") {
          setSimilarLoading(false);
        }
      } catch (err: unknown) {
        if (similarPollingRef.current) {
          clearInterval(similarPollingRef.current);
          similarPollingRef.current = null;
        }
        setSimilarLoading(false);
        setSimilarError(err instanceof Error ? err.message : "Unknown error");
        console.error("[similar] 폴링 중 에러:", err);
      }
    };

    pollSimilarStatus();
    similarPollingRef.current = setInterval(pollSimilarStatus, 3000);

    return () => {
      if (similarPollingRef.current) {
        clearInterval(similarPollingRef.current);
        similarPollingRef.current = null;
      }
    };
  }, [similarTask?.task_id, similarTask?.status]);

  // --- 분석 시점 변경 시 또는 초기 로드 시 자동으로 모든 분석 실행 ---
  useEffect(() => {
    if (!selectedTimestamp || !coinSymbol || !coinInfo) {
      return;
    }

    // LightGBM 및 차트 분석은 항상 실행
    handleModelExplain();
    handleChartExplain();
    handleSimilarChart();
    handleScoreChart();

    // Transformer는 지원하는 코인만 실행
    if (supportsTransformer) {
      handleTransformerExplain();
    }
  }, [selectedTimestamp, coinInfo]); // coinInfo도 의존성에 추가하여 초기 로드 시에도 실행

  // --- 핸들러 1: AI 모델 분석 (KeyError 해결 + Polling 시작 수정) ---
  const handleModelExplain = async () => {
    if (!coinSymbol) return; // coinSymbol이 없으면 실행 중지
    setModelLoading(true);
    setModelError(null);
    setModelTask(null);

    if (!selectedTimestamp) {
      setModelError("시점을 선택한 후 요청해 주세요.");
      setModelLoading(false);
      return;
    }
    const normalizedTimestamp = toHourPrecision(selectedTimestamp);
    const inferenceTime = convertKstToUtc(normalizedTimestamp);

    console.log("[model] 분석 요청 시간 (UTC 기준):", inferenceTime);

    try {
      const res = await fetchWithAuth("http://localhost:8000/explain/model/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_name: "LightGBM",
          coin_symbol: coinSymbol,
          timeframe: 60,
          inference_time: inferenceTime,
        }),
      });
      
      const data = await res.json(); 

      if (!res.ok) {
         console.error("[model] API 요청 실패:", data.detail || "알 수 없는 서버 에러");
         throw new Error(data.detail || "모델 분석 요청 실패");
      }
      
      const initialTaskStatus: ApiTaskResponse = {
        task_id: data.task_id,
        status: "PENDING", // Polling이 시작되도록 상태 주입
        results: null
      };

      console.log("[model] Task ID 수신 성공, 폴링 시작:", initialTaskStatus);
      setModelTask(initialTaskStatus); 

    } catch (err: unknown) {
      console.error("[model] handleExplainRequest CATCH 블록 에러:", err instanceof Error ? err.message : "Unknown error");
      setModelLoading(false);
      setModelError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  // --- 핸들러 1-1: Transformer 모델 분석 ---
  const handleTransformerExplain = async () => {
    if (!coinSymbol) return;
    setTransformerLoading(true);
    setTransformerError(null);
    setTransformerTask(null);

    if (!selectedTimestamp) {
      setTransformerError("시점을 선택한 후 요청해 주세요.");
      setTransformerLoading(false);
      return;
    }
    const normalizedTimestamp = toHourPrecision(selectedTimestamp);
    const inferenceTime = convertKstToUtc(normalizedTimestamp);

    console.log("[transformer] 분석 요청 시간 (UTC 기준):", inferenceTime);

    try {
      const res = await fetchWithAuth("http://localhost:8000/explain/model/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_name: "Transformer",
          coin_symbol: coinSymbol,
          timeframe: 60,
          inference_time: inferenceTime,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
         console.error("[transformer] API 요청 실패:", data.detail || "알 수 없는 서버 에러");
         throw new Error(data.detail || "Transformer 모델 분석 요청 실패");
      }

      const initialTaskStatus: ApiTaskResponse = {
        task_id: data.task_id,
        status: "PENDING",
        results: null
      };

      console.log("[transformer] Task ID 수신 성공, 폴링 시작:", initialTaskStatus);
      setTransformerTask(initialTaskStatus);

    } catch (err: unknown) {
      console.error("[transformer] handleExplainRequest CATCH 블록 에러:", err instanceof Error ? err.message : "Unknown error");
      setTransformerLoading(false);
      setTransformerError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  // --- 핸들러 2: 차트 기술적 분석 (Polling 시작 수정) ---
  const handleChartExplain = async () => {
    if (!coinSymbol) return; // coinSymbol이 없으면 실행 중지
    setChartLoading(true);
    setChartError(null);
    setChartTask(null);

    if (!selectedTimestamp) {
      setChartError("시점을 선택한 후 요청해 주세요.");
      setChartLoading(false);
      return;
    }
    const normalizedTimestamp = toHourPrecision(selectedTimestamp);
    const inferenceTime = convertKstToUtc(normalizedTimestamp);
    console.log("[chart] 분석 요청 시간 (UTC 기준):", inferenceTime);

    try {
      const res = await fetchWithAuth("http://localhost:8000/explain/chart/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          coin_symbol: coinSymbol,
          timeframe: 60,
          inference_time: inferenceTime,
        }),
      });

      const data = await res.json(); 

      if (!res.ok) {
         console.error("[chart] API 요청 실패:", data.detail || "알 수 없는 서버 에러");
        throw new Error(data.detail || "차트 기술적 분석 요청 실패");
      }

      const initialTaskStatus: ApiTaskResponse = {
        task_id: data.task_id,
        status: "PENDING", // Polling이 시작되도록 상태 주입
        results: null
      };

      console.log("[chart] Task ID 수신 성공, 폴링 시작:", initialTaskStatus);
      setChartTask(initialTaskStatus); 

    } catch (err: unknown) {
      console.error("[chart] handleChartExplain CATCH 블록 에러:", err instanceof Error ? err.message : "Unknown error");
      setChartLoading(false);
      setChartError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  const handleScoreChart = async () => {
    if (!coinSymbol) return;

    setScoreLoading(true);
    setScoreError(null);
    if (scorePollingRef.current) {
      clearInterval(scorePollingRef.current);
      scorePollingRef.current = null;
    }
    setScoreTask(null);

    if (!selectedTimestamp) {
      setScoreError("시점을 선택한 후 요청해 주세요.");
      setScoreLoading(false);
      return;
    }

    const normalizedTimestamp = toHourPrecision(selectedTimestamp);
    const inferenceTime = convertKstToUtc(normalizedTimestamp);

    console.log("[score] 분석 요청 시간 (UTC 기준):", inferenceTime);

    try {
      const response = await fetchWithAuth("http://localhost:8000/score-chart/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          coin_symbol: coinSymbol,
          timeframe: SCORE_TIMEFRAME,
          inference_time: inferenceTime,
          history_window: SCORE_HISTORY_WINDOW,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        console.error("[score] API 요청 실패:", data.detail || "알 수 없는 서버 에러");
        throw new Error(data.detail || "차트 점수 요청 실패");
      }

      setScoreTask({
        task_id: data.task_id,
        status: "PENDING",
        results: null,
      });
      console.log("[score] Task ID 수신 성공, 폴링 시작:", data.task_id);
    } catch (err: unknown) {
      console.error("[score] handleScoreChart CATCH 블록 에러:", err instanceof Error ? err.message : "Unknown error");
      setScoreLoading(false);
      setScoreError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  const handleSimilarChart = async () => {
    if (!coinSymbol || !coinInfo) return;

    setSimilarLoading(true);
    setSimilarError(null);
    if (similarPollingRef.current) {
      clearInterval(similarPollingRef.current);
      similarPollingRef.current = null;
    }
    setSimilarTask(null);

    if (!selectedTimestamp) {
      setSimilarError("시점을 선택한 후 요청해 주세요.");
      setSimilarLoading(false);
      return;
    }

    const normalizedTimestamp = toHourPrecision(selectedTimestamp);
    const inferenceTime = convertKstToUtc(normalizedTimestamp);

    console.log("[similar] 분석 요청 시간 (UTC 기준):", inferenceTime);

    try {
      const response = await fetchWithAuth("http://localhost:8000/explain/similar_chart/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          coin_symbol: coinSymbol,
          timeframe: 60,
          inference_time: inferenceTime,
          search_start: coinInfo.available_start,
          search_end: coinInfo.available_end,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        console.error("[similar] API 요청 실패:", data.detail || "알 수 없는 서버 에러");
        throw new Error(data.detail || "유사 차트 요청 실패");
      }

      setSimilarTask({
        task_id: data.task_id,
        status: "PENDING",
        results: null,
      });
      console.log("[similar] Task ID 수신 성공, 폴링 시작:", data.task_id);
    } catch (err: unknown) {
      console.error("[similar] handleSimilarChart CATCH 블록 에러:", err instanceof Error ? err.message : "Unknown error");
      setSimilarLoading(false);
      setSimilarError(err instanceof Error ? err.message : "Unknown error");
    }
  };
  
  const modelResults = modelTask?.results as ExplainModelResult | null;
  const transformerResults = transformerTask?.results as ExplainModelResult | null;
  const chartResults = chartTask?.results as ExplainChartResult | null;
  const similarResults = similarTask?.results as ExplainSimilarChartResult | null;

  // --- 렌더링 영역 ---
  return (
    <div className="container mx-auto p-8">
      <header className="mb-8">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <h1 className="text-4xl font-bold text-white">
              {coinSymbol} AI 분석
            </h1>
            <button
              onClick={() => setShowCoinSelector(!showCoinSelector)}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-white font-semibold"
            >
              코인 변경
            </button>
          </div>
          {coinSymbol && (
            <button
              onClick={() => handleToggleWatchlist(coinSymbol)}
              className={`px-4 py-2 rounded-lg font-semibold ${
                watchlist.includes(coinSymbol)
                  ? "bg-yellow-600 hover:bg-yellow-700 text-white"
                  : "bg-gray-700 hover:bg-gray-600 text-white"
              }`}
            >
              {watchlist.includes(coinSymbol) ? "★ 관심 코인" : "☆ 관심 코인 추가"}
            </button>
          )}
        </div>

        {/* 코인 선택기 */}
        {showCoinSelector && (
          <div className="mb-6 p-4 bg-gray-800 rounded-lg">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">코인 선택</h2>
              <button
                onClick={() => setShowCoinSelector(false)}
                className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
              >
                닫기
              </button>
            </div>

            {/* 관심 코인 */}
            {watchlist.length > 0 && (
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-gray-400 mb-2">관심 코인</h3>
                <div className="flex flex-wrap gap-2">
                  {watchlist.map((coin) => (
                    <button
                      key={coin}
                      onClick={() => {
                        router.push(`/coins/${coin}`);
                        setShowCoinSelector(false);
                      }}
                      className={`px-4 py-2 rounded-lg font-semibold transition ${
                        coin === coinSymbol
                          ? "bg-blue-600 text-white"
                          : "bg-gray-700 hover:bg-gray-600 text-white"
                      }`}
                    >
                      ★ {coin}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 모든 코인 */}
            <div>
              <h3 className="text-sm font-semibold text-gray-400 mb-2">모든 코인</h3>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2 max-h-64 overflow-y-auto">
                {availableCoins.map((coin) => (
                  <button
                    key={coin}
                    onClick={() => {
                      router.push(`/coins/${coin}`);
                      setShowCoinSelector(false);
                    }}
                    className={`px-3 py-2 rounded-lg font-semibold transition ${
                      coin === coinSymbol
                        ? "bg-blue-600 text-white"
                        : "bg-gray-700 hover:bg-gray-600 text-white"
                    }`}
                  >
                    {coin}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </header>

      {/* --- 1. 차트 및 날짜 선택 (TypeScript 에러 수정) --- */}
      <section className="p-6 bg-gray-800 rounded-lg mb-8">
        <h2 className="text-2xl font-semibold mb-4">분석 시점 선택</h2>
        {coinInfo ? (
          <div className="flex items-center gap-4">
            <input
              type="datetime-local"
              step={3600}
              value={selectedTimestamp}
              onChange={(e) => setSelectedTimestamp(e.target.value)}
              className="p-2 bg-gray-700 text-white rounded-lg border border-gray-600"
            />
          </div>
        ) : (
          <p className="text-gray-500">코인 정보 로딩 중...</p>
        )}
        
        {/* ★★★ coinSymbol이 string일 때만 차트를 렌더링 ★★★ */}
        <div className="bg-gray-700 rounded-lg min-h-[150px] mt-4">
          {coinSymbol ? (
            <HistoricalCandleChart 
              coinSymbol={coinSymbol} 
              timestamp={selectedTimestamp}
              highlightTimestamp={selectedTimestamp}
              height="400px"
            />
          ) : (
            <p className="p-4 text-gray-500 text-center">코인 정보 로딩 중...</p>
          )}
        </div>
      </section>
      
      {/* --- 2. 분석 기능 (탭) --- */}
      <section className="p-6 bg-gray-800 rounded-lg">
        <div className="flex overflow-hidden rounded-lg border border-gray-700 bg-gray-900">
          <button
            type="button"
            onClick={() => setActiveTab("lightgbm")}
            className={`flex-1 py-3 text-sm font-semibold transition ${
              activeTab === "lightgbm"
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:bg-gray-800 hover:text-white"
            }`}
          >
            LightGBM 모델
          </button>
          {supportsTransformer && (
            <button
              type="button"
              onClick={() => setActiveTab("transformer")}
              className={`flex-1 py-3 text-sm font-semibold transition ${
                activeTab === "transformer"
                  ? "bg-gray-800 text-white"
                  : "text-gray-400 hover:bg-gray-800 hover:text-white"
              }`}
            >
              Transformer 모델
            </button>
          )}
          <button
            type="button"
            onClick={() => setActiveTab("chart")}
            className={`flex-1 py-3 text-sm font-semibold transition ${
              activeTab === "chart"
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:bg-gray-800 hover:text-white"
            }`}
          >
            차트 기술적 분석
          </button>
        </div>

        <div className="mt-6 space-y-6">
          {activeTab === "lightgbm" ? (
            <div className="space-y-6">
              <div className="flex justify-between items-center">
                <p className="text-lg font-semibold text-white">LightGBM 모델 분석</p>
                <button
                  onClick={handleModelExplain}
                  disabled={modelLoading || !coinSymbol}
                  className={`px-4 py-2 font-bold text-white rounded-lg ${
                    (modelLoading ||
                      (modelTask?.status === "STARTED" || modelTask?.status === "PENDING") ||
                      !coinSymbol)
                      ? "bg-gray-600 cursor-not-allowed"
                      : "bg-blue-600 hover:bg-blue-700"
                  }`}
                >
                  {(modelLoading || (modelTask?.status === "STARTED" || modelTask?.status === "PENDING"))
                    ? "분석 중..."
                    : "분석 시작"}
                </button>
              </div>

              {/* 에러 메시지 */}
              {modelError && <p className="text-red-400 text-center">{modelError}</p>}

              {/* 로딩 메시지 */}
              {(modelLoading ||
                (modelTask?.status === "STARTED" || modelTask?.status === "PENDING")) && (
                <p className="text-gray-500 text-center">LightGBM AI가 분석 중입니다 (약 15~30초)...</p>
              )}

              {/* LightGBM 결과 */}
              {modelTask?.status === "SUCCESS" && modelResults && (
                <div className="space-y-4">
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <div className="text-center">
                      <p className="text-lg text-gray-400">모델 추천</p>
                      <p
                        className={`text-3xl font-bold ${getModelPercentileColor(
                          modelResults.prediction_percentile
                        )}`}
                      >
                        {getRecommendationLabel(modelResults.recommendation)}
                      </p>
                      <p className="text-sm text-gray-400">
                        <span
                          className={getModelPercentileColor(modelResults.prediction_percentile)}
                        >
                          예측 상위 {modelResults.prediction_percentile.toFixed(1)}%
                        </span>
                      </p>
                    </div>
                  </div>
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <h3 className="text-lg font-semibold mb-2">AI 분석 요약</h3>
                    <p className="text-gray-300 text-sm whitespace-pre-line">
                      {renderBoldText(modelResults.explanation_text)}
                    </p>
                  </div>
                </div>
              )}

              {/* LightGBM 상세 정보 (SHAP 등) */}
              {modelTask?.status === "SUCCESS" && modelResults && (
                <div className="space-y-4 p-4 bg-gray-800 rounded-lg border border-blue-500">
                  <h2 className="text-2xl font-bold text-blue-400">LightGBM 상세 분석</h2>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="p-4 bg-gray-700 rounded-lg">
                      <h3 className="text-xl font-semibold mb-2">SHAP 기여도</h3>
                      <ShapChart shapValues={modelResults.shap_values} />
                    </div>
                    <div className="p-4 bg-gray-700 rounded-lg">
                      <h3 className="text-xl font-semibold mb-2">Feature / SHAP 값</h3>
                      <div className="grid grid-cols-1 gap-2 text-sm text-gray-300">
                        {Object.entries(modelResults.shap_values)
                          .sort(([, a], [, b]) => Math.abs(b.value) - Math.abs(a.value))
                          .map(([featureKey, shapValueObj]) => {
                            const featureValueObj = modelResults.feature_values[featureKey];
                            // Use backend-provided descriptions with fallback
                            const displayName = shapValueObj.display_name || getFeatureInfo(featureKey, "model").name;
                            const interpretation = shapValueObj.interpretation || getFeatureInfo(featureKey, "model").description;
                            return (
                              <div
                                key={featureKey}
                                className="border border-gray-600 rounded-lg p-2 bg-gray-900"
                                title={interpretation}
                              >
                                <div className="flex justify-between text-xs text-gray-400 mb-1">
                                  <span>{displayName}</span>
                                  <span>SHAP {shapValueObj.value.toFixed(4)}</span>
                                </div>
                                <p className="text-base text-white">
                                  {Number.isFinite(featureValueObj?.value) ? featureValueObj.value.toFixed(4) : "-"}
                                </p>
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : activeTab === "transformer" ? (
            <div className="space-y-6">
              <div className="flex justify-between items-center">
                <p className="text-lg font-semibold text-white">Transformer 모델 분석</p>
                <button
                  onClick={handleTransformerExplain}
                  disabled={transformerLoading || !coinSymbol}
                  className={`px-4 py-2 font-bold text-white rounded-lg ${
                    (transformerLoading ||
                      (transformerTask?.status === "STARTED" || transformerTask?.status === "PENDING") ||
                      !coinSymbol)
                      ? "bg-gray-600 cursor-not-allowed"
                      : "bg-purple-600 hover:bg-purple-700"
                  }`}
                >
                  {(transformerLoading || (transformerTask?.status === "STARTED" || transformerTask?.status === "PENDING"))
                    ? "분석 중..."
                    : "분석 시작"}
                </button>
              </div>

              {/* 에러 메시지 */}
              {transformerError && <p className="text-red-400 text-center">{transformerError}</p>}

              {/* 로딩 메시지 */}
              {(transformerLoading ||
                (transformerTask?.status === "STARTED" || transformerTask?.status === "PENDING")) && (
                <p className="text-gray-500 text-center">Transformer AI가 분석 중입니다 (약 15~30초)...</p>
              )}

              {/* Transformer 결과 */}
              {transformerTask?.status === "SUCCESS" && transformerResults && (
                <div className="space-y-4">
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <div className="text-center">
                      <p className="text-lg text-gray-400">모델 추천</p>
                      <p
                        className={`text-3xl font-bold ${getModelPercentileColor(
                          transformerResults.prediction_percentile
                        )}`}
                      >
                        {getRecommendationLabel(transformerResults.recommendation)}
                      </p>
                      <p className="text-sm text-gray-400">
                        <span
                          className={getModelPercentileColor(transformerResults.prediction_percentile)}
                        >
                          예측 상위 {transformerResults.prediction_percentile.toFixed(1)}%
                        </span>
                      </p>
                    </div>
                  </div>
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <h3 className="text-lg font-semibold mb-2">AI 분석 요약</h3>
                    <p className="text-gray-300 text-sm whitespace-pre-line">
                      {renderBoldText(transformerResults.explanation_text)}
                    </p>
                  </div>
                </div>
              )}

              {/* Transformer 상세 정보 (SHAP 등) */}
              {transformerTask?.status === "SUCCESS" && transformerResults && (
                <div className="space-y-4 p-4 bg-gray-800 rounded-lg border border-purple-500">
                  <h2 className="text-2xl font-bold text-purple-400">Transformer 상세 분석</h2>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="p-4 bg-gray-700 rounded-lg">
                      <h3 className="text-xl font-semibold mb-2">SHAP 기여도</h3>
                      <ShapChart shapValues={transformerResults.shap_values} />
                    </div>
                    <div className="p-4 bg-gray-700 rounded-lg">
                      <h3 className="text-xl font-semibold mb-2">Feature / SHAP 값</h3>
                      <div className="grid grid-cols-1 gap-2 text-sm text-gray-300">
                        {Object.entries(transformerResults.shap_values)
                          .sort(([, a], [, b]) => Math.abs(b.value) - Math.abs(a.value))
                          .map(([featureKey, shapValueObj]) => {
                            const featureValueObj = transformerResults.feature_values[featureKey];
                            // Use backend-provided descriptions with fallback
                            const displayName = shapValueObj.display_name || getFeatureInfo(featureKey, "model").name;
                            const interpretation = shapValueObj.interpretation || getFeatureInfo(featureKey, "model").description;
                            return (
                              <div
                                key={featureKey}
                                className="border border-gray-600 rounded-lg p-2 bg-gray-900"
                                title={interpretation}
                              >
                                <div className="flex justify-between text-xs text-gray-400 mb-1">
                                  <span>{displayName}</span>
                                  <span>SHAP {shapValueObj.value.toFixed(4)}</span>
                                </div>
                                <p className="text-base text-white">
                                  {Number.isFinite(featureValueObj?.value) ? featureValueObj.value.toFixed(4) : "-"}
                                </p>
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <p className="text-lg font-semibold text-white">차트 기술적 분석</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={handleChartExplain}
                    disabled={chartLoading}
                    className={`px-4 py-2 font-bold text-white rounded-lg ${
                      (chartLoading ||
                        (chartTask?.status === "STARTED" || chartTask?.status === "PENDING"))
                        ? "bg-gray-600 cursor-not-allowed"
                        : "bg-blue-600 hover:bg-blue-700"
                    }`}
                  >
                    {(chartLoading ||
                      (chartTask?.status === "STARTED" || chartTask?.status === "PENDING"))
                      ? "차트 기술적 분석 진행 중..."
                      : "차트 기술적 분석"}
                  </button>
                  <button
                    onClick={handleSimilarChart}
                    disabled={similarLoading || !coinInfo}
                    className={`px-4 py-2 font-bold text-white rounded-lg ${
                      (similarLoading ||
                        (similarTask?.status === "STARTED" || similarTask?.status === "PENDING") ||
                        !coinInfo)
                        ? "bg-gray-600 cursor-not-allowed"
                        : "bg-purple-600 hover:bg-purple-700"
                    }`}
                  >
                    {(similarLoading ||
                      (similarTask?.status === "STARTED" || similarTask?.status === "PENDING"))
                      ? "유사 차트 분석 중..."
                      : "유사 차트 찾기"}
                  </button>
                  <button
                    onClick={handleScoreChart}
                    disabled={
                      scoreLoading ||
                      !coinSymbol ||
                      !selectedTimestamp
                    }
                    className={`px-4 py-2 font-bold text-white rounded-lg ${
                      scoreLoading
                        ? "bg-gray-600 cursor-not-allowed"
                        : "bg-emerald-600 hover:bg-emerald-500"
                    }`}
                  >
                    {scoreLoading ? "차트 점수 계산 중..." : "차트 점수 보기"}
                  </button>
                </div>
              </div>
              {chartError && <p className="text-red-400 text-center">{chartError}</p>}
              {(chartLoading ||
                (chartTask?.status === "STARTED" || chartTask?.status === "PENDING")) && (
                <p className="text-gray-500 text-center">차트 기술적 분석 중입니다...</p>
              )}
              <div className="mt-6 border-b border-gray-700">
                <div className="flex gap-2 text-sm">
                  {[
                    { key: "indicators", label: "기술적 지표/설명" },
                    { key: "similar", label: "유사한 차트" },
                    { key: "scores", label: "차트 점수" },
                  ].map((section) => (
                    <button
                      key={section.key}
                      type="button"
                      onClick={() =>
                        setChartSection(
                          section.key as "indicators" | "similar" | "scores"
                        )
                      }
                      className={`px-3 py-2 rounded-t-lg font-semibold transition ${
                        chartSection === section.key
                          ? "bg-gray-800 text-white border border-b-0 border-gray-700"
                          : "bg-gray-900 text-gray-400 hover:text-white"
                      }`}
                    >
                      {section.label}
                    </button>
                  ))}
                </div>
              </div>
              {chartSection === "indicators" && chartTask?.status === "SUCCESS" && chartResults && (
                <div className="space-y-6">
                  <div className="p-4 bg-gray-700 rounded-lg space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xl font-semibold">현재 차트의 기술적 지표</h3>
                      <span className="text-xs text-gray-400">
                        고/저/종가 등 주요 지표는 미리 계산된 값입니다.
                      </span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                      {Object.entries(chartResults.feature_values)
                        .sort(([, a], [, b]) => Math.abs(b.value) - Math.abs(a.value))
                        .map(([featureKey, featureValue]) => {
                          // Use backend-provided descriptions only
                          const displayName = featureValue.display_name || getFeatureInfo(featureKey, "chart").name;
                          const interpretation = featureValue.interpretation || "";

                          // 퍼센트 값인지 확인 (pct, change, return 등의 키워드 포함 시)
                          const isPercentage = featureKey.toLowerCase().includes('pct') ||
                                               featureKey.toLowerCase().includes('change') ||
                                               featureKey.toLowerCase().includes('return');

                          const displayValue = isPercentage
                            ? `${(featureValue.value * 100).toFixed(2)}%`
                            : featureValue.value.toFixed(2);

                          return (
                            <div
                              key={featureKey}
                              className="border border-gray-600 rounded-2xl bg-gray-900 p-3 space-y-1"
                            >
                              <div className="flex items-center justify-between text-sm text-gray-400">
                                <span>{displayName}</span>
                                <span className="text-xs uppercase tracking-wide">값</span>
                              </div>
                              <p
                                className="text-xl font-semibold text-white"
                              >
                                {displayValue}
                              </p>
                              <p className="text-xs text-gray-400">{interpretation}</p>
                            </div>
                          );
                        })}
                    </div>
                  </div>
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <h3 className="text-xl font-semibold mb-2">기술적 분석 요약</h3>
                    <p className="text-gray-300 whitespace-pre-line">
                      {renderBoldText(chartResults.explanation_text)}
                    </p>
                  </div>
                </div>
              )}
              {chartSection === "scores" && (
                <div className="space-y-4">
                  {scoreError && <p className="text-red-400 text-center">{scoreError}</p>}
                  {scoreLoading && (
                    <p className="text-gray-500 text-center">차트 점수를 계산 중입니다...</p>
                  )}
                  {scoreTask?.status === "SUCCESS" && scoreResults && (
                    <div className="p-4 bg-gray-700 rounded-lg space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="text-xl font-semibold">선택한 차트의 점수</h3>
                        <span className="text-xs text-gray-400">단위: 0~100 / -100~100</span>
                      </div>
                      <div className="overflow-x-auto">
                        <table className="min-w-full text-left">
                          <thead>
                            <tr className="text-xs uppercase tracking-wide text-gray-400">
                              <th className="py-2 pr-4 text-left">지표</th>
                              <th className="py-2 px-4 text-left">범위</th>
                              <th className="py-2 px-4 text-left">숫자</th>
                              <th className="py-2 px-4 text-left">백분위</th>
                              <th className="py-2 px-4 text-left">설명</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-800">
                            {SCORE_METRIC_META.map((metric) => {
                              const metricResult = scoreResults?.[metric.key];
                              const scoreValue = metricResult?.score;
                              const percentile = metricResult?.percentile;
                              const displayValue = Number.isFinite(scoreValue ?? NaN)
                                ? scoreValue!.toFixed(1)
                                : "-";
                              const displayPercentile = Number.isFinite(percentile ?? NaN)
                                ? `상위 ${percentile!.toFixed(1)}%`
                                : "-";
                              const explanationText =
                                metricResult?.explanation ?? metric.description;
                              return (
                                <tr key={metric.key} className="border-b border-gray-800">
                                  <td className="py-3 pr-4 font-semibold text-white">
                                    {metric.label}
                                  </td>
                                  <td className="py-3 px-4 text-xs uppercase tracking-wide text-gray-200">
                                    {metric.rangeHint}
                                  </td>
                                  <td className="py-3 px-4 text-3xl font-bold">
                                    <span
                                      className={getScoreValueClassName(
                                        scoreValue ?? NaN,
                                        metric.key
                                      )}
                                    >
                                      {displayValue}
                                    </span>
                                  </td>
                                  <td className="py-3 px-4 text-sm font-semibold text-blue-300">
                                    {displayPercentile}
                                  </td>
                                  <td className="py-3 px-4 text-xs text-gray-200 leading-relaxed">
                                <p className="text-sm text-gray-100 mb-1">
                                  {renderBoldText(explanationText)}
                                </p>
                                    <p className="text-xs text-gray-500">
                                      {metric.description}
                                    </p>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                  {!scoreResults && !scoreLoading && !scoreError && (
                    <p className="text-center text-gray-400">
                      차트 점수를 얻기 위해 버튼을 눌러주세요.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
        {activeTab === "chart" && chartSection === "similar" && (
          <div className="mt-6 space-y-6">
            {similarError && <p className="text-red-400 text-center">{similarError}</p>}
            {(similarLoading ||
              (similarTask?.status === "STARTED" || similarTask?.status === "PENDING")) && (
              <p className="text-gray-500 text-center">유사 차트를 찾는 중입니다...</p>
            )}
            {similarTask?.status === "SUCCESS" && similarResults && selectedTimestamp && coinSymbol && (
              <div className="space-y-6">
                {/* 1. 먼저 차트들을 보여줌 */}
                <div className="p-4 bg-gray-700 rounded-lg space-y-4">
                  <h3 className="text-xl font-semibold">가장 유사한 과거 시점</h3>
                  <div className="grid grid-cols-1 gap-4">
                    <div className="flex justify-center">
                      <div className="border border-blue-600 rounded-xl overflow-hidden bg-gray-900 w-full sm:w-1/2">
                        <div className="flex items-center justify-between px-4 py-2 text-xs text-gray-400">
                          <span>현재 시점 ({new Date(selectedTimestamp).toLocaleString()})</span>
                          <span className="text-blue-300">#현재 차트</span>
                        </div>
                        <div className="px-3 pb-3">
                          <HistoricalCandleChart
                            coinSymbol={coinSymbol}
                            timestamp={selectedTimestamp}
                            height="170px"
                            windowHours={12}
                            futureHours={0}
                            highlightTimestamp={selectedTimestamp}
                          />
                        </div>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {similarResults.top_similar_charts.map((chart, index) => (
                        !chart.timestamp || !coinSymbol ? null : (
                          <div
                            key={`${chart.timestamp}-${index}`}
                            className="border border-gray-600 rounded-xl overflow-hidden bg-gray-900"
                          >
                            <div className="flex items-center justify-between px-4 py-2 text-xs text-gray-400">
                              <span>
                                {index + 1}. {new Date(chart.timestamp).toLocaleString()}
                              </span>
                              <span>거리 {chart.distance.toFixed(3)}</span>
                            </div>
                            <div className="px-3 pb-3">
                              <HistoricalCandleChart
                                coinSymbol={coinSymbol}
                                timestamp={chart.timestamp}
                                height="170px"
                                windowHours={12}
                                futureHours={3}
                                highlightTimestamp={chart.timestamp}
                              />
                            </div>
                          </div>
                        )
                      ))}
                    </div>
                  </div>
                </div>

                {/* 2. 그 아래에 자연어 설명 */}
                <div className="p-4 bg-gray-700 rounded-lg">
                  <h3 className="text-xl font-semibold mb-2">유사 패턴 분석</h3>
                  <p className="text-gray-300 whitespace-pre-line">
                    {renderBoldText(similarResults.explanation_text)}
                  </p>
                </div>

                {/* 3. 마지막으로 지표 차이 */}
                <div className="p-4 bg-gray-700 rounded-lg space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xl font-semibold">주요 지표 차이 (상승 vs 하락)</h3>
                    <div className="text-xs text-gray-400">
                      <span className="text-sky-300">▲ 상승 {similarResults.similar_chart_stats.price_up_count}개</span>
                      {" / "}
                      <span className="text-rose-300">▼ 하락 {similarResults.similar_chart_stats.price_down_count}개</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {Object.entries(similarResults.similar_chart_stats.feature_stats)
                      .sort(([, a], [, b]) => Math.abs(b.pct_diff) - Math.abs(a.pct_diff))
                      .map(([featureKey, stats]) => {
                        const displayName = stats.display_name || getFeatureInfo(featureKey, "chart").name;
                        const interpretation = stats.interpretation || getFeatureInfo(featureKey, "chart").description;
                        const isUpHigher = stats.up_value > stats.down_value;
                        return (
                          <div
                            key={featureKey}
                            className="border border-gray-600 rounded-lg bg-gray-900 p-3"
                            title={interpretation}
                          >
                            <div className="text-sm font-semibold text-gray-300 mb-2">
                              {displayName}
                            </div>
                            <div className="space-y-1 text-xs">
                              <div className="flex justify-between">
                                <span className="text-sky-300">상승 시</span>
                                <span className="text-white">{stats.up_value.toFixed(2)}</span>
                              </div>
                              <div className="flex justify-between">
                                <span className="text-rose-300">하락 시</span>
                                <span className="text-white">{stats.down_value.toFixed(2)}</span>
                              </div>
                              <div className="flex justify-between pt-1 border-t border-gray-700">
                                <span className="text-gray-400">차이율</span>
                                <span className={`font-semibold ${
                                  isUpHigher ? "text-sky-300" : "text-rose-300"
                                }`}>
                                  {(stats.pct_diff * 100).toFixed(1)}%
                                </span>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </div>
              </div>
            )}
            {!similarResults && !similarLoading && !similarError && (
              <p className="text-center text-gray-400">
                유사 차트를 찾기 위해 버튼을 눌러주세요.
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}