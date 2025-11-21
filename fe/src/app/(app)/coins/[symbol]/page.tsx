// app/(app)/coins/[symbol]/page.tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchWithAuth } from "../../layout";
// 1. '설명 없음' 문제를 해결한 헬퍼 함수 임포트
import { getFeatureInfo } from "@/lib/featureDescriptions"; 
// 2. 업비트 과거 캔들 차트 컴포넌트 임포트
import HistoricalCandleChart from "@/components/HistoricalCandleChart";

// --- 타입 정의 ---
interface ExplainModelResult {
  prediction_percentile: number;
  recommendation: "Buy" | "Weak buy" | "Hold" | "Weak sell" | "Sell";
  shap_values: { [feature: string]: number };
  feature_values: { [feature: string]: number };
  reference_charts: { timestamp: string; similarity: number }[];
  explanation_text: string;
}

interface ExplainChartResult {
  similar_charts: { timestamp: string; distance: number }[];
  feature_values: { [feature: string]: number };
  explanation_text: string;
}

interface ScoreWithExplanation {
  score: number;
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
  const tzOffsetMs = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - tzOffsetMs).toISOString().slice(0, 16);
};

const isoToLocalDateTime = (iso: string) => formatDateTimeLocal(new Date(iso));

const toHourPrecision = (timestamp: string) => {
  if (!timestamp.includes("T")) {
    return timestamp;
  }
  const [date, time] = timestamp.split("T");
  const hour = time.slice(0, 2);
  return `${date}T${hour}:00`;
};

const formatKstNaiveString = (timestamp: string) => {
  if (!timestamp.includes("T")) {
    return timestamp;
  }
  return `${timestamp.replace("T", " ")}:00`;
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
function ShapChart({ shapValues }: { shapValues: { [key: string]: number } }) {
  const sortedShap = Object.entries(shapValues).sort(([, a], [, b]) => Math.abs(b) - Math.abs(a));
  const maxVal = Math.max(...sortedShap.map(entry => Math.abs(entry[1])), 1e-9);

  return (
    <div className="space-y-2">
      <h3 className="text-xl font-semibold mb-3">AI 추천 핵심 근거 (SHAP)</h3>
      {sortedShap.map(([featureKey, value]) => {
        // getFeatureInfo 함수로 한글 이름/설명 가져오기
        const { name, description } = getFeatureInfo(featureKey, "model");
        const isPositive = value > 0;
        const widthPercent = (Math.abs(value) / maxVal) * 100;
        
        return (
          <div key={featureKey} className="w-full">
            <div className="flex justify-between text-xs text-gray-300 mb-1">
              {/* title 속성으로 툴팁 추가 */}
              <span 
                className="cursor-help" 
                title={description} // 마우스를 올리면 설명이 툴팁으로 뜸
              >
                {name} {/* 한글 이름 표시 */}
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
  const coinSymbol = Array.isArray(params.symbol) ? params.symbol[0] : params.symbol;

  // 1. 데이터 상태
  const [coinInfo, setCoinInfo] = useState<CoinInfoResponse | null>(null);
  const [selectedTimestamp, setSelectedTimestamp] = useState<string>(() =>
    toHourPrecision(formatDateTimeLocal(new Date()))
  );

  // 2. '모델 분석' 상태
  const [modelTask, setModelTask] = useState<ApiTaskResponse | null>(null);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  // 3. '차트 분석' 상태
  const [chartTask, setChartTask] = useState<ApiTaskResponse | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"model" | "chart">("model");
  const [scoreTask, setScoreTask] = useState<ScoreChartApiTaskResponse | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [scoreError, setScoreError] = useState<string | null>(null);
  const scoreResults = scoreTask?.results ?? null;
  const scorePollingRef = useRef<NodeJS.Timeout | null>(null);
  const [chartSection, setChartSection] = useState<
    "indicators" | "similar" | "scores"
  >("indicators");

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
        setCoinInfo(data);
        const now = new Date();
        const maxDate = new Date(data.available_end);
        const maxLocal = toHourPrecision(isoToLocalDateTime(data.available_end));
        setSelectedTimestamp((prev) => {
          if (now > maxDate) {
            return maxLocal;
          }
          if (!prev) {
            return maxLocal;
          }
          const prevHour = toHourPrecision(prev);
          const prevDate = new Date(prevHour);
          if (prevDate > maxDate) {
            return maxLocal;
          }
          return prevHour;
        });
      } catch (e) {
        console.error("코인 정보 로드 실패", e);
      }
    };
    fetchCoinInfo();
  }, [coinSymbol]); // coinSymbol이 확정되면 실행

  // --- 공용 폴링(Polling) Hook (디버깅 로그 포함) ---
  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null; 

    const startPolling = (
      taskId: string,
      type: "model" | "chart",
      setTask: (task: ApiTaskResponse | null) => void,
      setLoading: (loading: boolean) => void,
      setError: (error: string | null) => void
    ) => {
      
      console.log(`[${type}] 폴링 시작... Task ID: ${taskId}`); 

      intervalId = setInterval(async () => {
        try {
          console.log(`[${type}] 작업 상태 확인 중... (ID: ${taskId})`);
          
          const res = await fetchWithAuth(
            `http://localhost:8000/explain/${type}/${taskId}`
          );
          if (!res.ok) throw new Error("분석 결과를 가져오는데 실패했습니다.");

          const data: ApiTaskResponse = await res.json();
          setTask(data); 

          console.log(`[${type}] 현재 상태:`, data.status);

          if (data.status === "SUCCESS" || data.status === "FAILURE") {
            if (intervalId) clearInterval(intervalId);
            setLoading(false);
            console.log(`[${type}] 폴링 종료.`);
            if (data.status === "FAILURE") {
              setError("AI 분석에 실패했습니다. (백엔드 에러)");
            }
          }
        } catch (err: any) {
          if (intervalId) clearInterval(intervalId);
          setLoading(false);
          setError(err.message);
          console.error(`[${type}] 폴링 중 에러:`, err);
        }
      }, 3000); 
    };

    if (modelTask?.task_id && (modelTask.status === "STARTED" || modelTask.status === "PENDING")) {
      startPolling(modelTask.task_id, "model", setModelTask, setModelLoading, setModelError);
    }
    if (chartTask?.task_id && (chartTask.status === "STARTED" || chartTask.status === "PENDING")) {
      startPolling(chartTask.task_id, "chart", setChartTask, setChartLoading, setChartError);
    }
    
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [modelTask, chartTask]); 

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
      } catch (err: any) {
        if (scorePollingRef.current) {
          clearInterval(scorePollingRef.current);
          scorePollingRef.current = null;
        }
        setScoreLoading(false);
        setScoreError(err.message);
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
    const inferenceTime = formatKstNaiveString(normalizedTimestamp);

    console.log("[model] 분석 요청 시간 (KST 기준):", inferenceTime);

    try {
      const res = await fetchWithAuth("http://localhost:8000/explain/model/", {
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

    } catch (err: any) {
      console.error("[model] handleExplainRequest CATCH 블록 에러:", err.message);
      setModelLoading(false);
      setModelError(err.message);
    }
  };

  // --- 핸들러 2: 차트 기술적 분석 (Polling 시작 수정) ---
  const handleChartExplain = async () => {
    if (!coinInfo || !coinSymbol) return; // coinInfo나 coinSymbol이 없으면 실행 중지
    setChartLoading(true);
    setChartError(null);
    setChartTask(null);

    if (!selectedTimestamp) {
      setChartError("시점을 선택한 후 요청해 주세요.");
      setChartLoading(false);
      return;
    }
    const normalizedTimestamp = toHourPrecision(selectedTimestamp);
    const inferenceTime = formatKstNaiveString(normalizedTimestamp);
    console.log("[chart] 분석 요청 시간 (KST 기준):", inferenceTime);

    try {
      const res = await fetchWithAuth("http://localhost:8000/explain/chart/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          coin_symbol: coinSymbol,
          timeframe: 60,
          inference_time: inferenceTime,
          start: coinInfo.available_start, 
          end: coinInfo.available_end,
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

    } catch (err: any) {
      console.error("[chart] handleChartExplain CATCH 블록 에러:", err.message);
      setChartLoading(false);
      setChartError(err.message);
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
    const inferenceTime = formatKstNaiveString(normalizedTimestamp);

    console.log("[score] 분석 요청 시간 (KST 기준):", inferenceTime);

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
    } catch (err: any) {
      console.error("[score] handleScoreChart CATCH 블록 에러:", err.message);
      setScoreLoading(false);
      setScoreError(err.message);
    }
  };
  
  const modelResults = modelTask?.results as ExplainModelResult | null;
  const chartResults = chartTask?.results as ExplainChartResult | null;

  // --- 렌더링 영역 ---
  return (
    <div className="container mx-auto p-8">
      <header className="mb-8">
        <Link href="/coins" className="text-blue-400 hover:text-blue-500">
          &larr; 코인 목록으로 돌아가기
        </Link>
        <h1 className="text-4xl font-bold text-center text-white mt-4">
          <span className="mr-4">🪙</span>
          {coinSymbol} AI 분석
        </h1>
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
              min={coinInfo ? isoToLocalDateTime(coinInfo.available_start) : undefined}
              max={coinInfo ? isoToLocalDateTime(coinInfo.available_end) : undefined}
              className="p-2 bg-gray-700 text-white rounded-lg border border-gray-600"
            />
            <p className="text-sm text-gray-400">
              (분석 가능 기간: {new Date(coinInfo.available_start).toLocaleDateString()} ~ 
              {new Date(coinInfo.available_end).toLocaleDateString()})
            </p>
          </div>
        ) : (
          <p className="text-gray-500">분석 가능 기간 로딩 중...</p>
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
            onClick={() => setActiveTab("model")}
            className={`flex-1 py-3 text-sm font-semibold transition ${
              activeTab === "model"
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:bg-gray-800 hover:text-white"
            }`}
          >
            AI 모델 분석
          </button>
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
          {activeTab === "model" ? (
            <div className="space-y-6">
              <div className="flex justify-between items-center">
                <p className="text-lg font-semibold text-white">AI 모델 분석</p>
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
                    : "모델 분석 실행"}
                </button>
              </div>
              {modelError && <p className="text-red-400 text-center">{modelError}</p>}
              {(modelLoading ||
                (modelTask?.status === "STARTED" || modelTask?.status === "PENDING")) && (
                <p className="text-gray-500 text-center">AI가 분석 중입니다 (약 15~30초)...</p>
              )}
              {modelTask?.status === "SUCCESS" && modelResults && (
                <div className="space-y-6">
              <div className="text-center">
                <p className="text-lg text-gray-400">모델 추천</p>
                <p
                  className={`text-4xl font-bold ${getModelPercentileColor(
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
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <h3 className="text-xl font-semibold mb-2">AI 분석 요약</h3>
                    <p className="text-gray-300 whitespace-pre-line">
                      {renderBoldText(modelResults.explanation_text)}
                    </p>
                  </div>
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <ShapChart shapValues={modelResults.shap_values} />
                  </div>
                  <div className="p-4 bg-gray-700 rounded-lg">
                    <h3 className="text-xl font-semibold mb-2">Feature / SHAP 값</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-gray-300">
                      {Object.entries(modelResults.shap_values)
                        .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
                        .map(([featureKey, shapValue]) => {
                          const featureValue = modelResults.feature_values[featureKey];
                          const { name, description } = getFeatureInfo(featureKey, "model");
                          return (
                            <div
                              key={featureKey}
                              className="border border-gray-600 rounded-lg p-2 bg-gray-900"
                              title={description}
                            >
                              <div className="flex justify-between text-xs text-gray-400 mb-1">
                                <span>{name}</span>
                                <span>SHAP {shapValue.toFixed(4)}</span>
                              </div>
                              <p className="text-base text-white">
                                {Number.isFinite(featureValue) ? featureValue.toFixed(4) : "-"}
                              </p>
                            </div>
                          );
                        })}
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
                    disabled={chartLoading || !coinInfo}
                    className={`px-4 py-2 font-bold text-white rounded-lg ${
                      (chartLoading ||
                        (chartTask?.status === "STARTED" || chartTask?.status === "PENDING") ||
                        !coinInfo)
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
                        .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
                        .map(([featureKey, value]) => {
                          const { name, description } = getFeatureInfo(featureKey, "chart");
                          return (
                            <div
                              key={featureKey}
                              className="border border-gray-600 rounded-2xl bg-gray-900 p-3 space-y-1"
                            >
                              <div className="flex items-center justify-between text-sm text-gray-400">
                                <span>{name}</span>
                                <span className="text-xs uppercase tracking-wide">값</span>
                              </div>
                              <p
                                className="text-xl font-semibold text-white"
                                title={description}
                              >
                                {value.toFixed(2)}
                              </p>
                              <p className="text-xs text-gray-400">{description}</p>
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
                              <th className="py-2 px-4 text-left">설명</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-800">
                            {SCORE_METRIC_META.map((metric) => {
                              const metricResult = scoreResults?.[metric.key];
                              const scoreValue = metricResult?.score;
                              const displayValue = Number.isFinite(scoreValue ?? NaN)
                                ? scoreValue!.toFixed(1)
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
        {activeTab === "chart" && chartSection === "similar" && chartTask?.status === "SUCCESS" && chartResults && selectedTimestamp && coinSymbol && (
          <div className="mt-6 space-y-6">
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
                          windowHours={24}
                          futureHours={0}
                          highlightTimestamp={selectedTimestamp}
                        />
                      </div>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {chartResults.similar_charts.map((chart, index) => (
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
                            windowHours={24}
                            futureHours={6}
                            highlightTimestamp={chart.timestamp}
                          />
                        </div>
                      </div>
                    )
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}