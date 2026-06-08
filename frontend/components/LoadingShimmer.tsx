"use client";

export function LoadingShimmer() {
  return (
    <div className="w-full max-w-md space-y-3" aria-label="Loading">
      <div className="h-4 w-3/4 rounded bg-slate-800 animate-pulse" />
      <div className="h-4 w-full rounded bg-slate-800 animate-pulse" />
      <div className="h-4 w-5/6 rounded bg-slate-800 animate-pulse" />
    </div>
  );
}
