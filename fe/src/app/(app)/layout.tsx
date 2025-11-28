// app/(app)/layout.tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

// 모든 API 요청에 자동으로 토큰을 넣어줄 fetch 래퍼 함수 (로그인 선택적)
export async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const token = localStorage.getItem("access_token");

  const headers = new Headers(options.headers);
  if (token) {
    headers.append("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    // 토큰이 만료되었거나 유효하지 않음 (로그인 페이지로 강제 이동하지 않음)
    localStorage.removeItem("access_token");
  }

  return response;
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<{ username: string } | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
      const token = localStorage.getItem("access_token");

      if (!token) {
        setIsLoading(false);
        return;
      }

      try {
        const response = await fetchWithAuth("http://localhost:8000/auth/me");

        if (response.ok) {
          const data = await response.json();
          setUser(data);
        }
      } catch (error) {
        console.error("인증 확인 실패:", error);
      } finally {
        setIsLoading(false);
      }
    };

    checkAuth();
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    setUser(null);
    window.location.href = "/";
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        로딩 중...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="bg-gray-800 border-b border-gray-700">
        <div className="container mx-auto px-8 py-4 flex items-center justify-between">
          <Link href="/" className="text-2xl font-bold text-blue-400 hover:text-blue-300">
            Crypto Lab
          </Link>
          <div className="flex items-center gap-4">
            {user ? (
              <>
                <span className="text-gray-300">환영합니다, {user.username}님</span>
                <button
                  onClick={handleLogout}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-white font-semibold"
                >
                  로그아웃
                </button>
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white font-semibold"
                >
                  로그인
                </Link>
                <Link
                  href="/register"
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded-lg text-white font-semibold"
                >
                  회원가입
                </Link>
              </>
            )}
          </div>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}