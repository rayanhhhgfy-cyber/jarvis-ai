"use client";

import FinancialDashboard from "../../components/FinancialDashboard";
import { ErrorBoundary } from "../../components/ErrorBoundary";

export default function FinancePage() {
  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Market Intelligence</h1>
          <p className="text-sm text-slate-400 mt-1">
            Real-time market data and arbitrage opportunities monitored by JARVIS.
          </p>
        </div>
        <FinancialDashboard />
      </div>
    </ErrorBoundary>
  );
}
