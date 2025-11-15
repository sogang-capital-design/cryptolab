// app/(app)/coins/[symbol]/page.tsx
"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchWithAuth } from "../../layout";
// 1. '설명 없음' 문제를 해결한 헬퍼 함수 임포트
import { getFeatureInfo } from "@/lib/featureDescriptions"; 
// 2. 업비트 과거 캔들 차트 컴포넌트 임포트
import HistoricalCandleChart from "@/components/HistoricalCandleChart";

// --- 타입 정의 ---
interface ExplainModelResult {
  prediction: number;
  shap_values: { [feature: string]: number };
  explanation_text: string;
  reference_charts: { timestamp: string; similarity: number }[];
}

interface ExplainChartResult {
  similar_charts: { timestamp: string; distance: number }[];
  feature_values: { [feature: string]: number };
  explanation_text: string;
}

interface ApiTaskResponse {
  task_id: string;
  status: string;
  results?: ExplainModelResult | ExplainChartResult | null;
}

interface CoinInfoResponse {
  available_start: string;
  available_end: string;
}

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
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split("T")[0]
  );

  // 2. '모델 분석' 상태
  const [modelTask, setModelTask] = useState<ApiTaskResponse | null>(null);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  // 3. '차트 분석' 상태
  const [chartTask, setChartTask] = useState<ApiTaskResponse | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

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
        if (new Date() > new Date(data.available_end)) {
          setSelectedDate(data.available_end.split("T")[0]);
        }
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

  // --- 핸들러 1: AI 모델 분석 (KeyError 해결 + Polling 시작 수정) ---
  const handleModelExplain = async () => {
    if (!coinSymbol) return; // coinSymbol이 없으면 실행 중지
    setModelLoading(true);
    setModelError(null);
    setModelTask(null);

    const inferenceDate = new Date(selectedDate + "T00:00:00Z"); 
    inferenceDate.setUTCHours(inferenceDate.getUTCHours() - 1); 
    inferenceDate.setUTCMinutes(0, 0, 0);
    const inferenceTime = inferenceDate.toISOString();

    console.log("[model] 분석 요청 시간 (UTC 1시간 전 정각):", inferenceTime);

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

  // --- 핸들러 2: 유사 차트 검색 (Polling 시작 수정) ---
  const handleChartExplain = async () => {
    if (!coinInfo || !coinSymbol) return; // coinInfo나 coinSymbol이 없으면 실행 중지
    setChartLoading(true);
    setChartError(null);
    setChartTask(null);

    const inferenceDate = new Date(selectedDate + "T00:00:00Z");
    const inferenceTime = inferenceDate.toISOString();
    console.log("[chart] 분석 요청 시간 (UTC 00시 정각):", inferenceTime);

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
         throw new Error(data.detail || "유사 차트 검색 요청 실패");
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
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              min={coinInfo.available_start.split("T")[0]}
              max={coinInfo.available_end.split("T")[0]}
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
              selectedDate={selectedDate} 
            />
          ) : (
            <p className="p-4 text-gray-500 text-center">코인 정보 로딩 중...</p>
          )}
        </div>
      </section>
      
      {/* --- 2. 분석 기능 (그리드) --- */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

        {/* --- 2-A. AI 모델 분석 (SHAP) --- */}
        <section className="p-6 bg-gray-800 rounded-lg">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-semibold">AI 모델 분석</h2>
            <button
              onClick={handleModelExplain}
              disabled={modelLoading || !coinSymbol}
              className={`px-4 py-2 font-bold text-white rounded-lg ${
                (modelLoading || (modelTask?.status === "STARTED" || modelTask?.status === "PENDING") || !coinSymbol)
                  ? "bg-gray-600 cursor-not-allowed"
                  : "bg-blue-600 hover:bg-blue-700"
              }`}
            >
              {(modelLoading || (modelTask?.status === "STARTED" || modelTask?.status === "PENDING")) ? "분석 중..." : "모델 분석 실행"}
            </button>
          </div>
          {/* 모델 분석 결과 */}
          {modelError && <p className="text-red-400 text-center">{modelError}</p>}
          {(modelLoading || (modelTask?.status === "STARTED" || modelTask?.status === "PENDING")) && 
            <p className="text-gray-500 text-center">AI가 분석 중입니다 (약 15~30초)...</p>
          }
          {modelTask?.status === "SUCCESS" && modelResults && (
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-lg text-gray-400">모델 예측값</p>
                <p className={`text-4xl font-bold ${modelResults.prediction > 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {modelResults.prediction > 0 ? "매수 성향" : "매도 성향"}
                  ({modelResults.prediction.toFixed(4)})
                </p>
              </div>
              <div className="p-4 bg-gray-700 rounded-lg">
                <h3 className="text-xl font-semibold mb-2">AI 분석 요약</h3>
                <p className="text-gray-300 whitespace-pre-line">{modelResults.explanation_text}</p>
              </div>
              <div className="p-4 bg-gray-700 rounded-lg">
                <ShapChart shapValues={modelResults.shap_values} />
              </div>
            </div>
          )}
        </section>

        {/* --- 2-B. 유사 차트 검색 --- */}
        <section className="p-6 bg-gray-800 rounded-lg">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-semibold">유사 차트 검색</h2>
            <button
              onClick={handleChartExplain}
              disabled={chartLoading || !coinInfo}
              className={`px-4 py-2 font-bold text-white rounded-lg ${
                (chartLoading || (chartTask?.status === "STARTED" || chartTask?.status === "PENDING") || !coinInfo)
                  ? "bg-gray-600 cursor-not-allowed"
                  : "bg-blue-600 hover:bg-blue-700"
              }`}
            >
              {(chartLoading || (chartTask?.status === "STARTED" || chartTask?.status === "PENDING")) ? "검색 중..." : "유사 차트 검색"}
            </button>
          </div>
          {/* 차트 분석 결과 */}
          {chartError && <p className="text-red-400 text-center">{chartError}</p>}
          {(chartLoading || (chartTask?.status === "STARTED" || chartTask?.status === "PENDING")) && 
            <p className="text-gray-500 text-center">유사 차트 검색 중입니다...</p>
          }
          {chartTask?.status === "SUCCESS" && chartResults && (
            <div className="space-y-6">
              <div className="p-4 bg-gray-700 rounded-lg">
                <h3 className="text-xl font-semibold mb-2">현재 차트의 기술적 지표</h3>
                <ul className="grid grid-cols-2 gap-2 text-sm">
                  {Object.entries(chartResults.feature_values).map(([featureKey, value]) => {
                    const { name, description } = getFeatureInfo(featureKey, "chart");
                    return (
                      <li 
                        key={featureKey} 
                        className="text-gray-300 cursor-help"
                        title={description} 
                      >
                        <strong>{name}:</strong> {value.toFixed(2)}
                      </li>
                    );
                  })}
                </ul>
              </div>
              <div className="p-4 bg-gray-700 rounded-lg">
                 <h3 className="text-xl font-semibold mb-2">가장 유사한 과거 시점</h3>
                 <ul className="space-y-2">
                  {chartResults.similar_charts.map((chart, index) => (
                    <li key={index} className="text-gray-400">
                      {index + 1}. {new Date(chart.timestamp).toLocaleString()} 
                      <span className="text-xs ml-2">(유사도: {chart.distance.toFixed(3)})</span>
                    </li>
                  ))}
                 </ul>
              </div>
              <div className="p-4 bg-gray-700 rounded-lg">
                <h3 className="text-xl font-semibold mb-2">기술적 분석 요약</h3>
                <p className="text-gray-300 whitespace-pre-line">{chartResults.explanation_text}</p>
              </div>
            </div>
          )}
        </section>

      </div>
    </div>
  );
}