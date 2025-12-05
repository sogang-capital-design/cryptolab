// src/lib/api.ts
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface OHLCVDataPoint {
  datetime_utc: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trade_count: number;
  price: number;
}

export interface OHLCVResponse {
  coin_symbol: string;
  interval: string;
  data: OHLCVDataPoint[];
}

export interface OHLCVRequest {
  coin_symbol: string;
  start_time: string; // ISO 8601 format
  end_time: string; // ISO 8601 format
  interval?: string; // default "1h"
}

export async function fetchOHLCV(params: OHLCVRequest): Promise<OHLCVResponse> {
  const response = await fetch(`${API_BASE_URL}/data/ohlcv`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(params),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(errorData.detail || `Failed to fetch OHLCV data: ${response.statusText}`);
  }

  return response.json();
}
