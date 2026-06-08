"use client";

import { useState, useEffect } from "react";

interface MarketData {
  symbol: string;
  price: number;
  change_24h: number;
  volume: string;
}

export default function FinancialDashboard() {
  const [data, setData] = useState<MarketData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/finance/arbitrage")
      .then((r) => r.json())
      .then((res) => {
        if (res.opportunities) setData(res.opportunities);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-24 bg-white/5 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (!data.length) {
    return (
      <div className="text-center text-white/50 py-12">
        No market data available.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
      {data.map((item) => (
        <div
          key={item.symbol}
          className="bg-white/5 backdrop-blur rounded-xl p-4 border border-white/10"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-lg font-semibold text-white">{item.symbol}</span>
            <span className="text-xs text-white/40">{item.volume}</span>
          </div>
          <div className="text-2xl font-bold text-white">
            ${item.price.toLocaleString()}
          </div>
          <div
            className={`text-sm mt-1 ${
              item.change_24h >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {item.change_24h >= 0 ? "+" : ""}
            {item.change_24h.toFixed(2)}% (24h)
          </div>
        </div>
      ))}
    </div>
  );
}
