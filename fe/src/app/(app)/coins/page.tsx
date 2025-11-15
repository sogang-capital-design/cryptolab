// app/(app)/coins/page.tsx
"use client";

import { useState, useEffect } from "react";
import Link from "next/link"; // 페이지 이동을 위한 Link 태그

// API 응답 타입
interface CoinListResponse {
  available_coin_symbols: string[];
}

export default function CoinsPage() {
  const [coins, setCoins] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  // 1. 페이지 로드 시, 코인 목록 API를 1번만 호출
  useEffect(() => {
    const fetchCoins = async () => {
      try {
        setLoading(true);
        // /data/list API는 인증이 필요 없으므로 일반 fetch 사용
        const response = await fetch("http://localhost:8000/data/list");
        
        if (!response.ok) {
          throw new Error("코인 목록을 불러오는데 실패했습니다.");
        }

        const data: CoinListResponse = await response.json();
        setCoins(data.available_coin_symbols); // ["ADA", "BTC", ...]

      } catch (error) {
        console.error("코인 목록 로드 실패:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchCoins();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        코인 목록 로딩 중...
      </div>
    );
  }

  return (
    <div className="container mx-auto p-8">
      <header className="mb-8">
        {/* 1. 메인 대시보드로 돌아가기 링크 */}
        <Link href="/" className="text-blue-400 hover:text-blue-500">
          &larr; 메인 대시보드로 돌아가기
        </Link>
        <h1 className="text-4xl font-bold text-center text-white mt-4">
          <span className="mr-4">🪙</span>
          코인 목록
        </h1>
        <p className="text-center text-gray-400 mt-2">
          분석할 코인을 선택하세요.
        </p>
      </header>

      {/* 2. 코인 목록을 그리드로 표시 */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        {coins.map((coinSymbol) => (
          // 3. 각 코인을 클릭하면 상세 페이지(/coins/BTC 등)로 이동
          <Link 
            href={`/coins/${coinSymbol}`} 
            key={coinSymbol} 
            passHref
          >
            <div className="flex items-center justify-center p-6 bg-gray-800 rounded-lg cursor-pointer hover:bg-gray-700 transition-colors">
              <h2 className="text-xl font-bold text-white">
                {coinSymbol}
              </h2>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}