// app/(app)/page.tsx
"use client";

import { useState, useEffect } from "react";
import { fetchWithAuth } from "./layout"; 
import Link from "next/link"; 

interface WatchlistResponse {
  coin_symbols: string[];
}

export default function MainDashboardPage() {
  const [watchlist, setWatchlist] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchWatchlist = async () => {
      try {
        setLoading(true);
        const watchlistRes = await fetchWithAuth("http://localhost:8000/watchlist");

        if (watchlistRes.ok) {
          const data: WatchlistResponse = await watchlistRes.json();
          setWatchlist(data.coin_symbols);
        } else {
          setWatchlist([]); 
        }

      } catch (error) {
        console.error("관심 코인 로딩 실패:", error);
        setWatchlist([]);
      } finally {
        setLoading(false);
      }
    };

    fetchWatchlist();
  }, []);

  return (
    <div className="container mx-auto p-8">
      <header className="text-center my-8">
        <h1 className="text-4xl font-bold text-blue-400">Crypto Lab</h1>
        <p className="text-gray-400 mt-2">메인 대시보드</p>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* --- 왼쪽: 내 관심코인 --- */}
        <section>
          <h2 className="text-3xl font-bold mb-6">내 관심코인</h2>
          <div className="p-6 bg-gray-800 rounded-lg min-h-[300px]">
            {loading ? (
              <p className="text-gray-500">로딩 중...</p>
            ) : watchlist && watchlist.length > 0 ? (
              <ul className="space-y-3">
                {watchlist.map((coin) => (
                  <li 
                    key={coin} 
                    className="p-4 bg-gray-700 rounded-lg text-lg font-medium hover:bg-gray-600 transition-colors"
                  >
                    {coin}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-gray-500">(아직 설정된 관심 코인이 없습니다.)</p>
            )}
          </div>
        </section>

        {/* --- 오른쪽: 메뉴 --- */}
        <section>
          <h2 className="text-3xl font-bold mb-6 invisible">메뉴</h2>
          <div className="flex flex-col gap-6">
            
            {/* ★★★ 코인 버튼 (min-h-[300px]로 수정됨) ★★★ */}
            <Link href="/coins" passHref>
              <div 
                className="flex items-center justify-start p-8 bg-gray-800 rounded-lg cursor-pointer min-h-[300px] hover:bg-gray-700 transition-colors"
              >
                <h2 className="text-3xl font-bold">
                  <span className="mr-4">🪙</span>
                  코인
                </h2>
              </div>
            </Link>
            
          </div>
        </section>
      </div>
    </div>
  );
}