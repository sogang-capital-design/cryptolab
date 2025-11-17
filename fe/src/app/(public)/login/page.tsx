// app/(public)/login/page.tsx
"use client";

import { useState } from "react";
import { useRouter } from 'next/navigation';

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    console.log("로그인 시도:", { email, name, password });

    try {
      const response = await fetch("http://localhost:8000/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, name, password }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        
        let errorMessage = "로그인에 실패했습니다. 입력 정보를 확인해주세요."; 
        
        if (errorData.detail === "Invalid credentials") {
          errorMessage = "이메일, 이름, 또는 비밀번호가 일치하지 않습니다.";
        } 
        else if (typeof errorData.detail === 'string') {
          errorMessage = errorData.detail;
        } 
        else if (Array.isArray(errorData.detail)) {
          errorMessage = errorData.detail[0].msg || errorMessage;
        }

        throw new Error(errorMessage);
      }

      const data = await response.json(); // { "access_token": "...", ... }
      localStorage.setItem("access_token", data.access_token);
      
      console.log("로그인 성공, 토큰 저장 완료:", data.access_token);
      
      router.push('/'); 

    } catch (err: any) {
      console.error(err);
      setError(err.message); 
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-900 text-gray-100">
      <div className="w-full max-w-md p-8 space-y-6 bg-gray-800 rounded-lg shadow-md">
        
        <h1 className="text-3xl font-bold text-center text-blue-400">
          Crypto Lab
        </h1>
        <h2 className="text-2xl font-bold text-center text-white">
          로그인
        </h2>

        <form className="space-y-6" onSubmit={handleSubmit}>
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-gray-300"
            >
              이메일 주소
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 mt-1 border border-gray-600 rounded-md shadow-sm bg-gray-700 text-white placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label
              htmlFor="name"
              className="block text-sm font-medium text-gray-300"
            >
              이름 (닉네임)
            </label>
            <input
              id="name"
              name="name"
              type="text"
              autoComplete="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 mt-1 border border-gray-600 rounded-md shadow-sm bg-gray-700 text-white placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-gray-300"
            >
              비밀번호
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 mt-1 border border-gray-600 rounded-md shadow-sm bg-gray-700 text-white placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {error && (
            <p className="text-sm text-red-400 text-center">{error}</p>
          )}

          <div>
            <button
              type="submit"
              className="w-full px-4 py-2 font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              로그인
            </button>
          </div>
        </form>

        <p className="text-sm text-center text-gray-400">
          계정이 없으신가요?{" "}
          <a href="/register" className="font-medium text-blue-400 hover:text-blue-500">
            회원가입하기
          </a>
        </p>

      </div>
    </div>
  );
}