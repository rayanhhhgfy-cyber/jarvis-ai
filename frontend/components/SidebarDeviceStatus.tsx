"use client";

import { Monitor, Smartphone } from "lucide-react";

export enum DeviceTypePill {
  DESKTOP = "desktop",
  MOBILE = "mobile",
}

type Props = {
  title: string;
  status: "online" | "offline";
  detail?: string;
  type: DeviceTypePill;
};

export function SidebarDeviceStatus({ title, status, detail, type }: Props) {
  const online = status === "online";
  const Icon = type === DeviceTypePill.MOBILE ? Smartphone : Monitor;

  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2.5">
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-lg ${
          online ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/10 text-rose-400"
        }`}
      >
        <Icon size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-slate-100">{title}</span>
          <span
            className={`inline-flex h-2 w-2 rounded-full ${
              online ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" : "bg-rose-500"
            }`}
            aria-hidden
          />
        </div>
        {detail ? <div className="truncate text-xs text-slate-500">{detail}</div> : null}
      </div>
      <span
        className={`text-xs font-semibold uppercase tracking-wide ${
          online ? "text-emerald-400" : "text-rose-400"
        }`}
      >
        {online ? "Online" : "Offline"}
      </span>
    </div>
  );
}
