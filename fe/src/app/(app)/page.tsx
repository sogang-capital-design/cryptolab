// app/(app)/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface CoinListResponse {
  available_coin_symbols: string[];
}

export default function MainPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchFirstCoin = async () => {
      try {
        const res = await fetch("http://localhost:8000/data/list");
        if (res.ok) {
          const data: CoinListResponse = await res.json();
          if (data.available_coin_symbols && data.available_coin_symbols.length > 0) {
            // 첫 번째 사용 가능한 코인으로 리다이렉트
            router.replace(`/coins/${data.available_coin_symbols[0]}`);
          } else {
            setLoading(false);
          }
        } else {
          setLoading(false);
        }
      } catch (error) {
        console.error("코인 목록 로드 실패:", error);
        setLoading(false);
      }
    };

    fetchFirstCoin();
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
      {loading ? "차트 페이지로 이동 중..." : "코인 목록을 불러올 수 없습니다."}
    </div>
  );
}