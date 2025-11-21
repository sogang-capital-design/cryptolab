// src/components/HistoricalCandleChart.tsx
"use client";

import { useState, useEffect } from "react";
// ★★★ 1. TimeSeriesScale을 제거하고 필요한 모듈만 임포트 ★★★
import { 
  Chart, 
  TimeScale,            // 시간 축 (X축)
  LinearScale,          // 선형 축 (Y축)
  PointElement,
  Tooltip,
  Legend
} from "chart.js";
import { CandlestickController, CandlestickElement, OhlcController, OhlcElement } from "chartjs-chart-financial";
import { Chart as ReactChartJs } from "react-chartjs-2";
import "chartjs-adapter-date-fns";

const currentLinePlugin = {
  id: "currentLine",
  beforeDraw(chart: Chart) {
    const ctx = chart.ctx;
    const pluginOptions = (chart.options?.plugins as any)?.currentLine;
    const value = pluginOptions?.value;
    if (value === undefined || value === null) return;
    if (!chart.chartArea) return;
    const xScale = chart.scales.x as any;
    if (!xScale?.getPixelForValue) return;
    const pixel = xScale.getPixelForValue(value);
    if (pixel < chart.chartArea.left || pixel > chart.chartArea.right) return;
    ctx.save();
    ctx.strokeStyle = pluginOptions?.color || "#38bdf8";
    ctx.lineWidth = pluginOptions?.lineWidth || 1;
    ctx.setLineDash(pluginOptions?.dash || [6, 4]);
    ctx.beginPath();
    ctx.moveTo(pixel, chart.chartArea.top);
    ctx.lineTo(pixel, chart.chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

// ★★★ 2. TimeSeriesScale을 제거하고 차트 등록 ★★★
Chart.register(
  TimeScale,
  LinearScale,
  PointElement,
  Tooltip,
  Legend,
  CandlestickController,
  CandlestickElement,
  OhlcController,
  OhlcElement,
  currentLinePlugin
);

// 업비트 캔들 API 응답 타입
interface UpbitCandle {
  market: string;
  candle_date_time_kst: string;
  opening_price: number;
  high_price: number;
  low_price: number;
  trade_price: number;
  candle_acc_trade_volume: number;
}

interface ChartProps {
  coinSymbol: string;
  timestamp?: string | null;
  windowHours?: number;
  futureHours?: number;
  height?: string;
  highlightTimestamp?: string | number | null;
}

export default function HistoricalCandleChart({
  coinSymbol,
  timestamp,
  windowHours = 24,
  futureHours = 0,
  height,
  highlightTimestamp,
}: ChartProps) {
  const [candles, setCandles] = useState<UpbitCandle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!coinSymbol || !timestamp) return;

    const fetchCandles = async () => {
      setLoading(true);
      setError(null);
      setCandles([]); 

      const toDateTime = new Date(timestamp as string);
      toDateTime.setMinutes(0, 0, 0);
      if (futureHours > 0) {
        toDateTime.setHours(toDateTime.getHours() + futureHours);
      }
      const toParam = toDateTime.toISOString(); // UTC
      const market = `KRW-${coinSymbol}`;

      try {
        const response = await fetch(
          `https://api.upbit.com/v1/candles/minutes/60?market=${market}&to=${toParam}&count=${windowHours + futureHours}`
        );
        if (!response.ok) {
          throw new Error("업비트 캔들 데이터를 불러오는데 실패했습니다.");
        }
        const data: UpbitCandle[] = await response.json();
        setCandles(data.reverse()); 
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchCandles();
  }, [coinSymbol, timestamp, windowHours]);

  // --- 차트 데이터 포맷팅 ---
  const chartData = {
    datasets: [
      {
        label: `${coinSymbol} ${windowHours}시간봉`,
        data: candles.map((candle) => ({
          x: new Date(candle.candle_date_time_kst).getTime(),
          o: candle.opening_price,
          h: candle.high_price,
          l: candle.low_price,
          c: candle.trade_price,
        })),
        color: {
          up: '#16c784', // 상승 (초록)
          down: '#ea3943', // 하락 (빨강)
          unchanged: '#999', // 보합
        },
      },
    ],
  };

  // --- 차트 옵션 ---
  const highlightMs = highlightTimestamp ? new Date(highlightTimestamp).getTime() : undefined;
  const chartOptions: any = {
    responsive: true,
    maintainAspectRatio: false, 
    parsing: false, 
    scales: {
      x: {
        type: "time", // "time" 타입은 TimeScale 모듈이 처리
        time: {
          unit: "hour", 
          displayFormats: {
            hour: "MM/dd HH:mm",
          },
        },
        ticks: { color: "#9CA3AF" }, 
        grid: { color: "#374151" }, 
      },
      y: {
        type: "linear", // "linear" 타입은 LinearScale 모듈이 처리
        ticks: { color: "#9CA3AF" },
        grid: { color: "#374151" }, 
      },
    },
    plugins: {
      legend: {
        display: false, 
      },
      tooltip: {
        mode: 'index',
        intersect: false,
      },
      currentLine: {
        value: highlightMs,
        color: "#38bdf8",
        lineWidth: 1,
        dash: [4, 4],
      },
    },
  };

  // --- 렌더링 ---
  if (!timestamp) {
    return (
      <div className="p-4 text-gray-500 text-center h-60 flex items-center justify-center">
        표시할 시점을 선택해 주세요.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-4 text-gray-500 text-center h-60 flex items-center justify-center">
        차트 데이터 로딩 중...
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-4 text-red-400 text-center h-60 flex items-center justify-center">
        {error}
      </div>
    );
  }
  if (candles.length === 0) {
    return (
      <div className="p-4 text-gray-500 text-center h-60 flex items-center justify-center">
        차트 데이터가 없습니다.
      </div>
    );
  }

  const containerHeight = height ?? "300px";
  return (
    <div className="p-4" style={{ height: containerHeight }}>
      <ReactChartJs type="candlestick" data={chartData} options={chartOptions} />
    </div>
  );
}