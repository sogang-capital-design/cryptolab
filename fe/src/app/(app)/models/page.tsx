// app/(app)/models/page.tsx
"use client";

import { useState, useEffect } from "react";
import { fetchWithAuth } from "./layout"; // 인증 레이아웃의 fetch 함수
import Link from "next/link";

// API 응답 타입
interface ModelListResponse {
  all_param_names: { [modelName: string]: string[] };
}
interface CoinListResponse {
  available_coin_symbols: string[];
}
interface ModelInfoResponse {
  hyperparam_schema: { [paramName: string]: any };
}

export default function ModelsPage() {
  // 1. 상태 변수 정의
  const [modelsData, setModelsData] = useState<ModelListResponse | null>(null);
  const [coins, setCoins] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedParam, setSelectedParam] = useState<string>("");
  const [selectedCoin, setSelectedCoin] = useState<string>("");

  const [schema, setSchema] = useState<ModelInfoResponse | null>(null);
  const [formData, setFormData] = useState<{ [key: string]: any }>({});
  
  const [loading, setLoading] = useState({
    page: true,
    schema: false,
  });

  // 2. [페이지 로드 시] 모델 목록과 코인 목록을 1번만 불러오기
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const [modelsRes, coinsRes] = await Promise.all([
          fetch("http://localhost:8000/models/list"),
          fetch("http://localhost:8000/data/list"),
        ]);

        if (modelsRes.ok) {
          const data: ModelListResponse = await modelsRes.json();
          setModelsData(data);
          // 첫 번째 모델을 기본값으로 선택
          const firstModel = Object.keys(data.all_param_names)[0];
          setSelectedModel(firstModel);
        }

        if (coinsRes.ok) {
          const data: CoinListResponse = await coinsRes.json();
          setCoins(data.available_coin_symbols);
          // 첫 번째 코인을 기본값으로 선택
          setSelectedCoin(data.available_coin_symbols[0]);
        }
      } catch (error) {
        console.error("초기 데이터 로드 실패:", error);
      } finally {
        setLoading((prev) => ({ ...prev, page: false }));
      }
    };
    fetchInitialData();
  }, []);

  // 3. [모델 선택 시] 상세 설정 폼(Schema)을 동적으로 불러오기
  useEffect(() => {
    if (!selectedModel) return;

    const fetchModelInfo = async () => {
      setLoading((prev) => ({ ...prev, schema: true }));
      try {
        const response = await fetch("http://localhost:8000/models/info", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_name: selectedModel }),
        });
        if (response.ok) {
          const data: ModelInfoResponse = await response.json();
          setSchema(data);
          // 스키마가 로드되면 폼 데이터 초기화
          setFormData({}); 
        } else {
          setSchema(null);
        }
      } catch (error) {
        console.error("모델 정보 로드 실패:", error);
        setSchema(null);
      } finally {
        setLoading((prev) => ({ ...prev, schema: false }));
      }
    };
    fetchModelInfo();
  }, [selectedModel]); // selectedModel이 바뀔 때마다 실행

  // --- 헬퍼 변수 ---
  const modelNames = modelsData ? Object.keys(modelsData.all_param_names) : [];
  const paramNames = modelsData && selectedModel ? modelsData.all_param_names[selectedModel] : [];
  
  // --- 이벤트 핸들러 ---
  const handleModelChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedModel(e.target.value);
    setSelectedParam(""); // 모델이 바뀌면 파라미터 초기화
    setSchema(null); // 스키마 초기화
  };

  const handleFormChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));
  };
  
  // --- 동적 폼 렌더링 함수 ---
  const renderDynamicForm = () => {
    if (loading.schema) return <p className="text-gray-500">상세 설정 로딩 중...</p>;
    if (!schema || Object.keys(schema.hyperparam_schema).length === 0) {
      return <p className="text-gray-500">이 모델은 추가 설정이 필요 없습니다.</p>;
    }

    return Object.entries(schema.hyperparam_schema).map(([key, info]) => (
      <div key={key}>
        <label htmlFor={key} className="block text-sm font-medium text-gray-300">
          {info.title || key}
          {info.type === 'number' && (
             <span className="text-gray-500 ml-2">(숫자)</span>
          )}
          {info.type === 'string' && (
             <span className="text-gray-500 ml-2">(문자)</span>
          )}
        </label>
        <input
          type={info.type === 'number' ? 'number' : 'text'}
          id={key}
          name={key}
          defaultValue={info.default}
          onChange={handleFormChange}
          className="w-full px-3 py-2 mt-1 border border-gray-600 rounded-md shadow-sm bg-gray-700 text-white placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500"
        />
        {info.description && <p className="mt-1 text-xs text-gray-400">{info.description}</p>}
      </div>
    ));
  };
  
  // --- 백테스팅 제출 핸들러 (다음 단계에서 구현) ---
  const handleBacktestSubmit = (e: React.FormEvent) => {
     e.preventDefault();
     alert("백테스팅 기능은 다음 단계에서 연동합니다!");
     // TODO:
     // 1. timeframe: 60 (고정)
     // 2. start_date, end_date (입력 받아야 함)
     // 3. POST /backtest/ 호출
     // 4. task_id 받고 폴링(polling) 시작
  }

  if (loading.page) {
    return <div className="p-4">페이지 로딩 중...</div>;
  }

  // --- 5. 최종 UI 렌더링 ---
  return (
    <div className="container mx-auto p-8">
      <header className="mb-8">
        <Link href="/" className="text-blue-400 hover:text-blue-500">
          &larr; 메인 대시보드로 돌아가기
        </Link>
        <h1 className="text-4xl font-bold text-center text-white mt-4">
          <span className="mr-4">🤖</span>
          모델 관리 및 백테스팅
        </h1>
      </header>
      
      <form onSubmit={handleBacktestSubmit} className="space-y-8">
        {/* -- 1. 기본 선택 영역 -- */}
        <section className="p-6 bg-gray-800 rounded-lg">
          <h2 className="text-2xl font-semibold mb-6">1. 기본 설정</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* 1-1. 모델 선택 */}
            <div>
              <label htmlFor="model-select" className="block text-sm font-medium text-gray-300">
                모델 선택
              </label>
              <select
                id="model-select"
                value={selectedModel}
                onChange={handleModelChange}
                className="mt-1 block w-full p-2 border border-gray-600 rounded-md bg-gray-700 text-white"
              >
                {modelNames.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
            {/* 1-2. 파라미터 세트 선택 */}
            <div>
              <label htmlFor="param-select" className="block text-sm font-medium text-gray-300">
                파라미터 세트
              </label>
              <select
                id="param-select"
                value={selectedParam}
                onChange={(e) => setSelectedParam(e.target.value)}
                disabled={paramNames.length === 0}
                className="mt-1 block w-full p-2 border border-gray-600 rounded-md bg-gray-700 text-white"
              >
                <option value="">-- 선택 --</option>
                {paramNames.map((param) => (
                  <option key={param} value={param}>{param}</option>
                ))}
              </select>
            </div>
            {/* 1-3. 코인 선택 */}
            <div>
              <label htmlFor="coin-select" className="block text-sm font-medium text-gray-300">
                코인 선택
              </label>
              <select
                id="coin-select"
                value={selectedCoin}
                onChange={(e) => setSelectedCoin(e.target.value)}
                className="mt-1 block w-full p-2 border border-gray-600 rounded-md bg-gray-700 text-white"
              >
                {coins.map((coin) => (
                  <option key={coin} value={coin}>{coin}</option>
                ))}
              </select>
            </div>
          </div>
        </section>

        {/* -- 2. 상세 설정 (동적 폼) -- */}
        <section className="p-6 bg-gray-800 rounded-lg">
          <h2 className="text-2xl font-semibold mb-6">2. 상세 설정 (자동 생성)</h2>
          <div className="space-y-4">
            {renderDynamicForm()}
          </div>
        </section>

        {/* -- 3. 백테스팅 실행 -- */}
        <section className="p-6 bg-gray-800 rounded-lg">
          <h2 className="text-2xl font-semibold mb-6">3. 백테스팅 실행</h2>
          <p className="text-gray-400 mb-4">
            시간 단위(Timeframe)는 <strong>60분</strong>으로 고정됩니다.
          </p>
          
          {/* TODO: 날짜 선택기(Date Picker) 라이브러리 필요 */}
          <div className="text-gray-500 mb-4">
            (여기에 '시작 날짜'와 '종료 날짜'를 선택하는 Date Picker가 들어가야 합니다.)
          </div>

          <button
            type="submit"
            className="w-full px-6 py-3 font-bold text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
          >
            백테스팅 시작하기
          </button>
        </section>
      </form>
    </div>
  );
}