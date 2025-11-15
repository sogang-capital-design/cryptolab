"use client";

import { useState } from "react";
import type { Market } from "@/types/upbit";
import Ticker from "./Ticker";

export default function MarketInfo({ markets }: { markets: Market[] }) {
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
      <section className="md:col-span-1 p-4 border rounded-lg">
        <h2 className="text-2xl font-semibold mb-4">코인 목록</h2>
        <div className="max-h-96 overflow-y-auto">
          <ul>
            {markets.map((market) => (
              <li
                key={market.market}
                onClick={() => setSelectedMarket(market)}
                className={`p-2 rounded cursor-pointer ${
                  selectedMarket?.market === market.market
                    ? "bg-blue-600 text-white"
                    : "hover:bg-gray-100"
                }`}
              >
                <strong>{market.korean_name}</strong>
                <span className="text-xs text-gray-500 ml-2">
                  {market.market}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="md:col-span-2 p-4 border rounded-lg">
        {/* Ticker 컴포넌트에 선택된 마켓 객체 전체를 전달 */}
        <Ticker selectedMarket={selectedMarket} />
      </section>
    </div>
  );
}