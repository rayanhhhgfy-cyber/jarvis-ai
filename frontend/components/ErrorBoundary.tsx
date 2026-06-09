"use client";
import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

type Props = { children: ReactNode; fallback?: ReactNode };
type State = { hasError: boolean; error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <AlertTriangle size={40} className="text-rose-400 mb-4" />
          <h2 className="text-lg font-semibold text-slate-200 mb-2">Something went wrong</h2>
          <p className="text-sm text-slate-400 mb-4 max-w-md">
            {this.state.error?.message || "An unexpected error occurred"}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="flex items-center gap-2 rounded-lg bg-jarvis-500/20 px-4 py-2 text-sm text-jarvis-300 hover:bg-jarvis-500/30 border border-jarvis-500/30 transition-colors"
          >
            <RefreshCw size={16} />
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
