// app/(app)/layout.tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// 모든 API 요청에 자동으로 토큰을 넣어줄 fetch 래퍼 함수 (권장)
export async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const token = localStorage.getItem("access_token");

  const headers = new Headers(options.headers);
  if (token) {
    headers.append("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) { // 401 Unauthorized
    // 토큰이 만료되었거나 유효하지 않음
    localStorage.removeItem("access_token");
    // window.location.href = '/login'; // 페이지 강제 이동
    throw new Error("Unauthorized");
  }
  
  return response;
}


export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const checkAuth = async () => {
      const token = localStorage.getItem("access_token");

      if (!token) {
        router.replace("/login"); // 토큰 없으면 로그인 페이지로
        return;
      }

      try {
        // 2. 토큰이 유효한지 /auth/me API로 확인
        const response = await fetchWithAuth("http://localhost:8000/auth/me");
        
        if (response.ok) {
          setIsLoggedIn(true); // 유효한 토큰, 로그인 상태 인정
        } else {
          throw new Error("Invalid token");
        }
      } catch (error) {
        console.error("인증 실패:", error);
        localStorage.removeItem("access_token");
        router.replace("/login"); // 유효하지 않으면 로그인 페이지로
      }
    };

    checkAuth();
  }, [router]);

  // 1. 인증 확인 중...
  if (!isLoggedIn) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        로그인 정보 확인 중...
      </div>
    );
  }

  // 2. 인증 성공!
  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* TODO: 여기에 공통 헤더나 사이드바를 추가할 수 있습니다. */}
      {/* <header>...</header> */}
      <main>{children}</main>
    </div>
  );
}