"use client";

import React, { useState, useEffect } from "react";
import {
  Cpu,
  Folder,
  Download,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  FolderOpen,
  Plus,
  Loader2,
  ArrowRight,
  Settings,
  Info,
  ExternalLink,
} from "lucide-react";

interface InstalledMod {
  name: string;
  filename: string;
  installed_at: number;
  url: string;
  files: string[];
}

interface GameStatus {
  game_id: string;
  name: string;
  detected: boolean;
  game_dir: string;
  mod_dir: string;
  installed_mods: InstalledMod[];
  file_types: string[];
}

export default function ModsPage() {
  const [games, setGames] = useState<GameStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeGameId, setActiveGameId] = useState<string | null>(null);
  
  // Install states
  const [modUrl, setModUrl] = useState("");
  const [installing, setInstalling] = useState(false);
  const [installStatus, setInstallStatus] = useState<{ type: "success" | "error" | "info"; message: string } | null>(null);

  // Path override states
  const [editingPath, setEditingPath] = useState(false);
  const [customPath, setCustomPath] = useState("");
  const [updatingPath, setUpdatingPath] = useState(false);

  useEffect(() => {
    fetchGames();
  }, []);

  const fetchGames = async () => {
    try {
      const res = await fetch("/api/mods/games");
      if (res.ok) {
        const data = await res.json();
        setGames(data);
        if (data.length > 0 && !activeGameId) {
          setActiveGameId(data[0].game_id);
          setCustomPath(data[0].game_dir);
        } else if (activeGameId) {
          const updatedActive = data.find((g: GameStatus) => g.game_id === activeGameId);
          if (updatedActive) {
            setCustomPath(updatedActive.game_dir);
          }
        }
      }
    } catch (err) {
      console.error("Failed to fetch games:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleInstall = async () => {
    if (!activeGameId || !modUrl.trim()) return;

    setInstalling(true);
    setInstallStatus({ type: "info", message: "Starting download and installation..." });

    try {
      const res = await fetch("/api/mods/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_id: activeGameId, url: modUrl }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        setInstallStatus({ type: "success", message: data.message });
        setModUrl("");
        fetchGames(); // Reload list to show newly installed mod
      } else {
        setInstallStatus({ type: "error", message: data.detail || data.message || "Failed to install mod." });
      }
    } catch (err: any) {
      setInstallStatus({ type: "error", message: err.message || "An unexpected error occurred." });
    } finally {
      setInstalling(false);
    }
  };

  const handleUninstall = async (modName: string) => {
    if (!activeGameId) return;

    if (!confirm(`Are you sure you want to uninstall the mod "${modName}"? This will delete its files.`)) {
      return;
    }

    try {
      const res = await fetch("/api/mods/uninstall", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_id: activeGameId, mod_name: modName }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        alert(data.message);
        fetchGames();
      } else {
        alert(data.detail || data.message || "Failed to uninstall mod.");
      }
    } catch (err: any) {
      alert("Error: " + err.message);
    }
  };

  const handleUpdatePath = async () => {
    if (!activeGameId) return;
    setUpdatingPath(true);

    try {
      const res = await fetch("/api/mods/config-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_id: activeGameId, path: customPath }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        setEditingPath(false);
        fetchGames();
      } else {
        alert(data.detail || "Failed to update path.");
      }
    } catch (err: any) {
      alert("Error updating path: " + err.message);
    } finally {
      setUpdatingPath(false);
    }
  };

  const activeGame = games.find((g) => g.game_id === activeGameId);

  return (
    <div className="flex h-[calc(100vh-64px)] gap-6 overflow-hidden">
      {/* LEFT SIDEBAR: Games list */}
      <div className="w-64 shrink-0 border-r border-slate-800/80 bg-slate-950/40 p-4 flex flex-col min-h-0 rounded-2xl">
        <h3 className="text-sm font-semibold text-slate-400 mb-3 flex items-center gap-1.5">
          <Cpu size={14} className="text-jarvis-400" />
          Supported Games
        </h3>

        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="text-slate-600 animate-spin" size={20} />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto space-y-2 pr-1 custom-scrollbar">
            {games.map((game) => (
              <button
                key={game.game_id}
                onClick={() => {
                  setActiveGameId(game.game_id);
                  setCustomPath(game.game_dir);
                  setEditingPath(false);
                  setInstallStatus(null);
                }}
                className={`w-full text-left rounded-xl p-3 border text-xs transition-all flex flex-col gap-1.5 ${
                  activeGameId === game.game_id
                    ? "border-jarvis-500/30 bg-jarvis-500/5 text-slate-100"
                    : "border-slate-800/50 bg-slate-900/30 text-slate-400 hover:border-slate-700/50 hover:bg-slate-900/50"
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <span className="font-semibold">{game.name}</span>
                  <span
                    className={`h-2 w-2 rounded-full ${
                      game.detected ? "bg-emerald-500 shadow-[0_0_8px_#10b981]" : "bg-red-500/50"
                    }`}
                    title={game.detected ? "Installed game detected" : "Game directory not found"}
                  />
                </div>
                <span className="text-[10px] text-slate-500 truncate block w-full">
                  Mods: {game.installed_mods.length}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* CENTER WORKSPACE */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-y-auto custom-scrollbar pr-2 pb-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-jarvis-500/20 to-violet-500/20 border border-jarvis-500/20 shadow-md">
            <Settings size={20} className="text-jarvis-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
              Universal Smart Modder
            </h1>
            <p className="text-xs text-slate-500">
              Download and install mods automatically into your game directories.
            </p>
          </div>
        </div>

        {activeGame ? (
          <div className="space-y-6">
            {/* 1. Game Status Summary & Directory overrides */}
            <div className="border border-slate-800/80 bg-slate-900/20 rounded-2xl p-5 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h2 className="text-md font-bold text-slate-200">{activeGame.name} Configuration</h2>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full border ${
                        activeGame.detected
                          ? "bg-emerald-500/10 border-emerald-500/25 text-emerald-400"
                          : "bg-red-500/10 border-red-500/25 text-red-400"
                      }`}
                    >
                      {activeGame.detected ? "✓ Detected" : "⚠ Not Detected"}
                    </span>
                    <span className="text-[10px] text-slate-500">
                      Types: {activeGame.file_types.join(", ")}
                    </span>
                  </div>
                </div>

                <button
                  onClick={() => setEditingPath(!editingPath)}
                  className="self-start sm:self-center text-[10px] font-semibold text-jarvis-400 hover:text-jarvis-300 flex items-center gap-1 hover:underline"
                >
                  <FolderOpen size={11} />
                  {editingPath ? "Cancel Editing" : "Change Directory"}
                </button>
              </div>

              {/* Edit Path Input */}
              {editingPath ? (
                <div className="space-y-2 border-t border-slate-800/50 pt-3">
                  <label className="text-[10px] text-slate-400 font-semibold block">
                    Edit Game Installation Folder
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={customPath}
                      onChange={(e) => setCustomPath(e.target.value)}
                      placeholder="C:\SteamLibrary\steamapps\common\..."
                      className="flex-1 rounded-xl border border-slate-700/50 bg-slate-950/40 px-3 py-2 text-xs text-slate-200 focus:border-jarvis-500/50 focus:outline-none"
                    />
                    <button
                      onClick={handleUpdatePath}
                      disabled={updatingPath || !customPath.trim()}
                      className="rounded-xl bg-jarvis-500 hover:bg-jarvis-600 disabled:opacity-40 px-4 py-2 text-xs font-semibold text-white flex items-center gap-1.5"
                    >
                      {updatingPath && <Loader2 size={12} className="animate-spin" />}
                      Save
                    </button>
                  </div>
                  <p className="text-[10px] text-slate-500">
                    Make sure this points to the game's root installation folder. Jarvis will look for the mod subfolder relative to this path.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 border-t border-slate-800/50 pt-3 text-xs">
                  <div>
                    <span className="text-slate-500 font-medium block">Game Location:</span>
                    <span className="text-slate-300 font-mono text-[10px] block mt-0.5 break-all">
                      {activeGame.game_dir || "(Not Configured)"}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium block">Mod Target Folder:</span>
                    <span className="text-slate-300 font-mono text-[10px] block mt-0.5 break-all">
                      {activeGame.mod_dir || "(Same as game folder)"}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* 2. Mod Installer Form */}
            <div className="border border-slate-800/80 bg-slate-900/10 rounded-2xl p-5">
              <h3 className="text-xs font-bold text-slate-300 flex items-center gap-1.5 mb-2.5">
                <Download size={13} className="text-jarvis-400" />
                One-Click Mod Installer
              </h3>
              
              <div className="space-y-3">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={modUrl}
                    onChange={(e) => setModUrl(e.target.value)}
                    placeholder="Paste direct download URL to mod (.zip, .jar, .tmod)..."
                    className="flex-1 rounded-xl border border-slate-700/50 bg-slate-950/20 px-4 py-3 text-xs text-slate-200 focus:border-jarvis-500/50 focus:outline-none placeholder:text-slate-600"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleInstall();
                    }}
                  />
                  <button
                    onClick={handleInstall}
                    disabled={installing || !modUrl.trim()}
                    className="rounded-xl bg-gradient-to-r from-jarvis-500 to-jarvis-600 hover:shadow-jarvis-500/30 shadow-md px-5 py-3 text-xs font-semibold text-white disabled:opacity-40 flex items-center gap-1.5 transition-all"
                  >
                    {installing ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <ArrowRight size={13} />
                    )}
                    Install
                  </button>
                </div>

                <div className="flex items-start gap-2 bg-slate-950/20 border border-slate-800/40 p-3 rounded-xl">
                  <Info size={14} className="text-slate-500 shrink-0 mt-0.5" />
                  <p className="text-[10px] text-slate-500 leading-relaxed">
                    Ensure this is a direct file download link. When triggered, Jarvis downloads the mod, unzips/places files into <strong>{activeGame.name}</strong>'s mod folder automatically.
                  </p>
                </div>

                {/* Progress Status Logs */}
                {installStatus && (
                  <div
                    className={`rounded-xl border p-4 flex gap-2.5 items-start text-xs ${
                      installStatus.type === "success"
                        ? "border-emerald-500/25 bg-emerald-500/5 text-emerald-400"
                        : installStatus.type === "error"
                        ? "border-red-500/25 bg-red-500/5 text-red-400"
                        : "border-slate-800/50 bg-slate-900/40 text-slate-400"
                    }`}
                  >
                    {installStatus.type === "success" && <CheckCircle2 size={14} className="shrink-0 mt-0.5" />}
                    {installStatus.type === "error" && <AlertTriangle size={14} className="shrink-0 mt-0.5" />}
                    {installStatus.type === "info" && <Loader2 size={14} className="animate-spin shrink-0 mt-0.5" />}
                    <div>
                      <p className="font-semibold capitalize text-[11px]">
                        {installStatus.type === "info" ? "Installing Mod..." : `${installStatus.type}!`}
                      </p>
                      <p className="text-[10px] text-slate-400 mt-0.5 leading-relaxed">{installStatus.message}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* 3. Installed Mods Table */}
            <div className="border border-slate-800/80 bg-slate-900/20 rounded-2xl p-5">
              <h3 className="text-xs font-bold text-slate-300 flex items-center gap-1.5 mb-4">
                <Folder size={13} className="text-jarvis-400" />
                Active Installed Mods ({activeGame.installed_mods.length})
              </h3>

              {activeGame.installed_mods.length === 0 ? (
                <div className="flex flex-col items-center justify-center p-8 text-center text-slate-500 border border-dashed border-slate-800 rounded-xl bg-slate-950/20">
                  <FolderOpen size={20} className="mb-2 text-slate-700" />
                  <p className="text-[11px]">No mods registered for this game yet.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {activeGame.installed_mods.map((mod) => (
                    <div
                      key={mod.name}
                      className="rounded-xl border border-slate-800/60 bg-slate-900/30 p-4 flex items-center justify-between gap-4"
                    >
                      <div className="min-w-0">
                        <span className="font-semibold text-xs text-slate-200 block truncate">
                          {mod.name}
                        </span>
                        <span className="text-[9px] text-slate-500 block truncate mt-0.5">
                          File: {mod.filename}
                        </span>
                        <div className="flex items-center gap-2 mt-1.5">
                          {mod.url && (
                            <a
                              href={mod.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[9px] text-slate-400 hover:text-slate-200 flex items-center gap-0.5 hover:underline"
                            >
                              Source <ExternalLink size={8} />
                            </a>
                          )}
                          <span className="text-[9px] text-slate-600">
                            Files: {mod.files.length} items
                          </span>
                        </div>
                      </div>

                      <button
                        onClick={() => handleUninstall(mod.name)}
                        className="rounded-lg border border-red-500/20 bg-red-500/5 hover:bg-red-500/10 p-2 text-red-400 transition-colors"
                        title="Uninstall Mod"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center p-12 text-center border border-slate-800/80 rounded-2xl bg-slate-900/10">
            <Cpu className="text-slate-700 mb-2" size={32} />
            <p className="text-xs text-slate-500">Select a game from the left list to configure.</p>
          </div>
        )}
      </div>
    </div>
  );
}
