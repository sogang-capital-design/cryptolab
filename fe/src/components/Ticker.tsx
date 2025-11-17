"use client";

import { useEffect, useState } from "react";
import type { Market } from "@/types/upbit";

// 업비트 웹소켓에서 받아오는 Ticker 데이터 타입을 정의합니다.
interface UpbitTickerData {
  type: "ticker";
  code: string;
  trade_price: number;
  change: "RISE" | "FALL" | "EVEN";
  signed_change_rate: number;
  acc_trade_volume_24h: number;
  acc_trade_price_24h: number;
}

export default function Ticker({
  selectedMarket,
}: {
  selectedMarket: Market | null;
}) {
  const [tickerData, setTickerData] = useState<UpbitTickerData | null>(null);
  const [connectionStatus, setConnectionStatus] = useState("대기 중...");

  useEffect(() => {
    if (!selectedMarket) {
      setConnectionStatus("코인을 선택해주세요.");
      setTickerData(null);
      return;
    }

    setConnectionStatus("연결 시도 중...");
    const ws = new WebSocket("wss://api.upbit.com/websocket/v1");

    ws.onopen = () => {
      setConnectionStatus("연결 성공!");
      const subscribeMsg = [
        { ticket: "capstone-project" },
        { type: "ticker", codes: [selectedMarket.market] },
      ];
      ws.send(JSON.stringify(subscribeMsg));
    };

    ws.onmessage = async (event) => {
      const text = await event.data.text();
      const data: UpbitTickerData = JSON.parse(text);
      setTickerData(data);
    };

    ws.onerror = (error) => {
      console.error("WebSocket Error:", error);
      setConnectionStatus("연결 실패!");
    };

    ws.onclose = () => {
      setConnectionStatus("연결 끊어짐");
    };

    return () => {
      ws.close();
    };
  }, [selectedMarket]);
  
  // UI 렌더링 부분
  if (!selectedMarket || !tickerData) {
    return <div className="p-4 text-gray-400">{connectionStatus}</div>;
  }

  const priceColor =
    tickerData.change === "RISE"
      ? "text-red-500"
      : tickerData.change === "FALL"
      ? "text-blue-500"
      : "text-white";

  return (
    <div className="p-4 space-y-2">
      <h3 className="text-2xl font-bold">
        {selectedMarket.korean_name} 실시간 정보
      </h3>
      <p className={`text-3xl font-bold ${priceColor}`}>
        {tickerData.trade_price.toLocaleString()} KRW
      </p>
      <div className="text-sm">
        <p>
          전일 대비:{" "}
          <span className={priceColor}>
            {(tickerData.signed_change_rate * 100).toFixed(2)}%
          </span>
        </p>
        <p>
          거래량(24H): <span>{tickerData.acc_trade_volume_24h.toFixed(3)}</span>
        </p>
        <p>
          거래대금(24H):{" "}
          <span>
            {(tickerData.acc_trade_price_24h / 1_000_000).toLocaleString(
              undefined,
              { maximumFractionDigits: 0 }
            )}
            백만
          </span>
        </p>
      </div>
    </div>
  );
}
