"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Upload,
  Film,
  Flame,
  Download,
  Share2,
  Play,
  RotateCcw,
  Sparkles,
  TrendingUp,
  Cpu,
  Scissors,
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
  Video,
  ChevronRight,
  FileText,
} from "lucide-react";

interface ViralScore {
  hook_strength: number;
  pacing: number;
  emotion: number;
  shareability: number;
  overall: number;
  reasoning: string;
}

interface GeneratedClip {
  clip_id: string;
  filename: string;
  path: string;
  start: number;
  end: number;
  duration: number;
  title: string;
  transcript: string;
  platform: string;
  video_url: string;
  thumbnail_url: string | null;
  viral_score: ViralScore | null;
}

interface ClipJob {
  job_id: string;
  original_filename: string;
  status: string; // uploaded | transcribing | analyzing | cutting | scoring | complete | error
  progress: number;
  message: string;
  created_at: string;
  full_transcript?: string;
  clips?: GeneratedClip[];
  error?: string | null;
}

const PLATFORMS = [
  { id: "tiktok", label: "TikTok (9:16)", activeColor: "border-pink-500/50 text-pink-400 bg-pink-500/5" },
  { id: "youtube_shorts", label: "YouTube Shorts (9:16)", activeColor: "border-red-500/50 text-red-400 bg-red-500/5" },
  { id: "reels", label: "Instagram Reels (9:16)", activeColor: "border-purple-500/50 text-purple-400 bg-purple-500/5" },
  { id: "original", label: "Original Aspect Ratio", activeColor: "border-emerald-500/50 text-emerald-400 bg-emerald-500/5" },
];

export default function ClipsPage() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(["tiktok", "youtube_shorts"]);
  const [currentJob, setCurrentJob] = useState<ClipJob | null>(null);
  const [history, setHistory] = useState<ClipJob[]>([]);
  const [clips, setClips] = useState<GeneratedClip[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [activeClipId, setActiveClipId] = useState<string | null>(null);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Load history on mount
  useEffect(() => {
    fetchHistory();
    return () => stopPolling();
  }, []);

  // Poll status if job is processing
  useEffect(() => {
    if (currentJob && !["complete", "error"].includes(currentJob.status)) {
      startPolling(currentJob.job_id);
    } else {
      stopPolling();
      if (currentJob?.status === "complete") {
        fetchResults(currentJob.job_id);
        fetchHistory(); // Refresh history
      }
    }
  }, [currentJob?.status]);

  const fetchHistory = async () => {
    try {
      const res = await fetch("/api/clips/history");
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
      }
    } catch (err) {
      console.error("Failed to fetch clip history:", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const fetchResults = async (jobId: string) => {
    try {
      const res = await fetch(`/api/clips/${jobId}/results`);
      if (res.ok) {
        const data = await res.json();
        setClips(data);
        if (data.length > 0) {
          setActiveClipId(data[0].clip_id);
        }
      }
    } catch (err) {
      console.error("Failed to fetch clip results:", err);
    }
  };

  const startPolling = (jobId: string) => {
    stopPolling();
    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/clips/${jobId}/status`);
        if (res.ok) {
          const data = await res.json();
          setCurrentJob(data);
        }
      } catch (err) {
        console.error("Error polling job status:", err);
      }
    }, 2000);
  };

  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile.type.startsWith("video/")) {
        setFile(droppedFile);
      }
    }
  };

  const togglePlatform = (id: string) => {
    setSelectedPlatforms((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  };

  const handleUploadAndProcess = async () => {
    if (!file) return;

    setUploading(true);
    setUploadProgress(0);
    setClips([]);
    
    const formData = new FormData();
    formData.append("file", file);

    try {
      // 1. Upload Video
      const uploadRes = await fetch("/api/clips/upload", {
        method: "POST",
        body: formData,
      });

      if (!uploadRes.ok) throw new Error("Upload failed");
      const job = await uploadRes.json();
      setCurrentJob(job);
      setUploading(false);

      // 2. Start Processing
      const processRes = await fetch(`/api/clips/${job.job_id}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platforms: selectedPlatforms }),
      });

      if (!processRes.ok) throw new Error("Processing initialization failed");
      const updatedJob = await processRes.json();
      setCurrentJob(updatedJob);
    } catch (err: any) {
      setUploading(false);
      alert(err.message || "An error occurred during clip creation");
    }
  };

  const selectHistoryJob = async (job: ClipJob) => {
    setCurrentJob(job);
    setClips([]);
    if (job.status === "complete") {
      fetchResults(job.job_id);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "complete":
        return <CheckCircle2 className="text-emerald-400 shrink-0" size={16} />;
      case "error":
        return <XCircle className="text-red-400 shrink-0" size={16} />;
      case "uploaded":
        return <Clock className="text-slate-500 shrink-0" size={16} />;
      default:
        return <Loader2 className="text-jarvis-400 animate-spin shrink-0" size={16} />;
    }
  };

  const activeClip = clips.find((c) => c.clip_id === activeClipId);

  return (
    <div className="flex h-[calc(100vh-64px)] gap-6 overflow-hidden">
      {/* LEFT SIDEBAR: History */}
      <div className="w-64 shrink-0 border-r border-slate-800/80 bg-slate-950/40 p-4 flex flex-col min-h-0 rounded-2xl">
        <h3 className="text-sm font-semibold text-slate-400 mb-3 flex items-center gap-1.5">
          <Film size={14} className="text-jarvis-400" />
          Clip Archives
        </h3>
        
        {loadingHistory ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="text-slate-600 animate-spin" size={20} />
          </div>
        ) : history.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center text-center p-4">
            <Video className="text-slate-700 mb-2" size={24} />
            <span className="text-[11px] text-slate-600">No clips processed yet.</span>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto space-y-2 pr-1 custom-scrollbar">
            {history.map((job) => (
              <button
                key={job.job_id}
                onClick={() => selectHistoryJob(job)}
                className={`w-full text-left rounded-xl p-3 border text-xs transition-all flex flex-col gap-1.5 ${
                  currentJob?.job_id === job.job_id
                    ? "border-jarvis-500/30 bg-jarvis-500/5 text-slate-100"
                    : "border-slate-800/50 bg-slate-900/30 text-slate-400 hover:border-slate-700/50 hover:bg-slate-900/50"
                }`}
              >
                <div className="flex items-start justify-between gap-2 w-full">
                  <span className="font-medium truncate max-w-[150px]">
                    {job.original_filename}
                  </span>
                  {getStatusIcon(job.status)}
                </div>
                <div className="flex items-center justify-between text-[10px] text-slate-500">
                  <span>{job.job_id}</span>
                  <span>
                    {new Date(job.created_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </div>
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
            <Flame size={20} className="text-jarvis-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
              Autonomous Clip Machine
              <span className="rounded bg-jarvis-500/10 px-1.5 py-0.5 text-[10px] text-jarvis-400 border border-jarvis-500/20 font-normal">
                BETA
              </span>
            </h1>
            <p className="text-xs text-slate-500">
              Extract high-engagement highlights, generate subtitles, and score virality for TikTok, Reels, and Shorts.
            </p>
          </div>
        </div>

        {/* 1. UPLOADER & CONFIGS (If no active job OR job is complete/error, show config options) */}
        {(!currentJob || currentJob.status === "complete" || currentJob.status === "error") && (
          <div className="grid grid-cols-1 md:grid-cols-12 gap-5 mb-6">
            {/* Drag & Drop Box */}
            <div className="md:col-span-7">
              <div
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-2xl flex flex-col items-center justify-center p-8 text-center cursor-pointer transition-all h-[240px] ${
                  file
                    ? "border-jarvis-500/40 bg-jarvis-500/5"
                    : "border-slate-800 bg-slate-900/20 hover:border-slate-700/60 hover:bg-slate-900/30"
                }`}
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={(e) => e.target.files && setFile(e.target.files[0])}
                  accept="video/*"
                  className="hidden"
                />
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-800/80 mb-4 border border-slate-700/50">
                  {file ? (
                    <Video size={20} className="text-jarvis-400" />
                  ) : (
                    <Upload size={20} className="text-slate-400 animate-pulse" />
                  )}
                </div>
                {file ? (
                  <>
                    <p className="text-xs font-semibold text-slate-200 mb-1 max-w-[300px] truncate">
                      {file.name}
                    </p>
                    <p className="text-[10px] text-slate-500">
                      {(file.size / 1024 / 1024).toFixed(1)} MB • Click to change
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-xs font-medium text-slate-300 mb-1">
                      Drag and drop your video here
                    </p>
                    <p className="text-[10px] text-slate-500 max-w-[220px]">
                      Supports MP4, MOV, or WEBM up to 100MB
                    </p>
                  </>
                )}
              </div>
            </div>

            {/* Platform preset selector */}
            <div className="md:col-span-5 flex flex-col justify-between border border-slate-800/80 bg-slate-900/20 rounded-2xl p-5">
              <div>
                <h3 className="text-xs font-semibold text-slate-400 mb-3 flex items-center gap-1.5">
                  <Cpu size={12} className="text-jarvis-400" />
                  Choose Platforms
                </h3>
                <div className="space-y-2">
                  {PLATFORMS.map((plat) => {
                    const isSelected = selectedPlatforms.includes(plat.id);
                    return (
                      <button
                        key={plat.id}
                        onClick={() => togglePlatform(plat.id)}
                        className={`w-full text-left rounded-xl p-3 border text-xs transition-all flex items-center justify-between ${
                          isSelected
                            ? `${plat.activeColor} border-current`
                            : "border-slate-800 bg-slate-950/20 text-slate-500 hover:border-slate-800/80 hover:text-slate-400"
                        }`}
                      >
                        <span>{plat.label}</span>
                        <div
                          className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center ${
                            isSelected ? "border-current bg-current/20" : "border-slate-800"
                          }`}
                        >
                          {isSelected && <div className="w-1.5 h-1.5 rounded-full bg-current" />}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              <button
                onClick={handleUploadAndProcess}
                disabled={!file || selectedPlatforms.length === 0 || uploading}
                className="w-full mt-4 flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-jarvis-500 to-jarvis-600 px-5 py-3 text-xs font-semibold text-white shadow-lg shadow-jarvis-500/20 hover:shadow-jarvis-500/40 disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:scale-[1.01] active:scale-[0.99]"
              >
                {uploading ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <Scissors size={14} />
                    Extract Clip Highlights
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* 2. PIPELINE PROGRESS TRACKER */}
        {currentJob && !["complete", "error"].includes(currentJob.status) && (
          <div className="border border-slate-800/80 bg-slate-900/30 backdrop-blur-md rounded-2xl p-6 mb-6">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h3 className="text-xs font-semibold text-slate-300">
                  Processing: {currentJob.original_filename}
                </h3>
                <p className="text-[10px] text-slate-500 mt-0.5 flex items-center gap-1.5">
                  <Loader2 size={10} className="animate-spin text-jarvis-400" />
                  {currentJob.message}
                </p>
              </div>
              <span className="text-xs font-bold text-jarvis-400">{currentJob.progress}%</span>
            </div>

            {/* Progress bar */}
            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden mb-6">
              <div
                className="h-full bg-gradient-to-r from-jarvis-500 to-violet-500 transition-all duration-500"
                style={{ width: `${currentJob.progress}%` }}
              />
            </div>

            {/* Pipeline Stage Indicators */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { id: "transcribing", label: "Whisper STT", activeWhen: ["transcribing"] },
                { id: "analyzing", label: "Highlight Detection", activeWhen: ["analyzing"] },
                { id: "cutting", label: "FFmpeg Rendering", activeWhen: ["cutting"] },
                { id: "scoring", label: "Virality Predictor", activeWhen: ["scoring"] },
              ].map((stage, idx) => {
                const isRunning = currentJob.status === stage.id;
                const isPast =
                  ["complete", "error", "scoring", "cutting", "analyzing", "transcribing"].indexOf(
                    currentJob.status
                  ) > idx;
                
                return (
                  <div
                    key={stage.id}
                    className={`rounded-xl p-3 border text-xs flex flex-col gap-1 transition-all ${
                      isRunning
                        ? "border-jarvis-500/30 bg-jarvis-500/5 text-slate-200 animate-pulse"
                        : isPast
                        ? "border-emerald-500/10 bg-emerald-500/5 text-emerald-400/80"
                        : "border-slate-800/40 bg-slate-900/10 text-slate-600"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-[10px] uppercase tracking-wider">
                        Stage {idx + 1}
                      </span>
                      {isRunning && <Loader2 size={10} className="animate-spin text-jarvis-400" />}
                      {isPast && <CheckCircle2 size={10} className="text-emerald-400" />}
                    </div>
                    <span className="text-[11px] truncate">{stage.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ERROR STATE */}
        {currentJob?.status === "error" && (
          <div className="border border-red-500/20 bg-red-500/5 rounded-2xl p-5 mb-6 flex gap-3 items-start">
            <XCircle className="text-red-400 shrink-0 mt-0.5" size={16} />
            <div>
              <h4 className="text-xs font-semibold text-red-300">Processing Failed</h4>
              <p className="text-[11px] text-red-400/80 mt-1">{currentJob.error || currentJob.message}</p>
              <button
                onClick={() => setCurrentJob(null)}
                className="mt-3 text-[10px] font-semibold text-slate-400 hover:text-slate-200 flex items-center gap-1"
              >
                <RotateCcw size={10} /> Reset Form
              </button>
            </div>
          </div>
        )}

        {/* 3. CLIPS LAYOUT (Split View once job is complete and clips are loaded) */}
        {currentJob?.status === "complete" && clips.length > 0 && (
          <div className="flex flex-col gap-6">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <span className="text-xs font-semibold text-slate-400">
                Generated Highlights ({clips.length})
              </span>
              <button
                onClick={() => {
                  setCurrentJob(null);
                  setFile(null);
                  setClips([]);
                }}
                className="text-[10px] font-semibold text-jarvis-400 hover:text-jarvis-300 flex items-center gap-1 hover:underline"
              >
                <Upload size={10} /> Process New Video
              </button>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* List of Clips (Left 5 cols) */}
              <div className="lg:col-span-5 space-y-3">
                {clips.map((clip) => {
                  const isSelected = activeClipId === clip.clip_id;
                  return (
                    <button
                      key={clip.clip_id}
                      onClick={() => setActiveClipId(clip.clip_id)}
                      className={`w-full text-left rounded-2xl p-4 border transition-all flex flex-col gap-2 ${
                        isSelected
                          ? "border-jarvis-500/40 bg-jarvis-500/5 shadow-lg shadow-jarvis-500/5"
                          : "border-slate-800/60 bg-slate-900/20 hover:border-slate-800 hover:bg-slate-900/40"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3 w-full">
                        <div className="min-w-0">
                          <span className="font-semibold text-xs text-slate-200 block truncate">
                            {clip.title}
                          </span>
                          <span className="text-[10px] text-slate-500 block mt-0.5">
                            Duration: {clip.duration}s ({clip.start.toFixed(1)}s - {clip.end.toFixed(1)}s)
                          </span>
                        </div>
                        {clip.viral_score && (
                          <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-orange-500/10 text-orange-400 border border-orange-500/20 text-[10px] font-bold">
                            <Flame size={10} />
                            {clip.viral_score.overall}%
                          </div>
                        )}
                      </div>
                      
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[9px] text-slate-400 capitalize">
                          {clip.platform.replace("_", " ")}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Clip Details & Player (Right 7 cols) */}
              <div className="lg:col-span-7">
                {activeClip ? (
                  <div className="space-y-5">
                    {/* HTML5 Video Player */}
                    <div className="relative rounded-2xl overflow-hidden bg-black border border-slate-800/80 shadow-2xl flex items-center justify-center max-h-[480px]">
                      <video
                        key={activeClip.video_url} // Force reload on source change
                        src={activeClip.video_url}
                        controls
                        className="w-full h-full max-h-[480px] object-contain"
                        poster={activeClip.thumbnail_url || undefined}
                      />
                    </div>

                    {/* Actions Row */}
                    <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
                      <div>
                        <h2 className="text-sm font-bold text-slate-200">{activeClip.title}</h2>
                        <span className="text-[10px] text-slate-500 mt-1 capitalize block">
                          Format: {activeClip.platform.replace("_", " ")} presets applied
                        </span>
                      </div>
                      <a
                        href={activeClip.video_url}
                        download={activeClip.filename}
                        className="flex items-center gap-1.5 rounded-xl bg-slate-800 border border-slate-700/80 hover:bg-slate-700/80 px-4 py-2.5 text-[11px] font-semibold text-slate-300 hover:text-white transition-colors"
                      >
                        <Download size={12} />
                        Download MP4
                      </a>
                    </div>

                    {/* Viral Insights */}
                    {activeClip.viral_score && (
                      <div className="border border-slate-800/80 bg-slate-900/10 rounded-2xl p-5 space-y-4">
                        <div className="flex items-center justify-between">
                          <h3 className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                            <TrendingUp size={12} className="text-orange-400" />
                            Virality Breakdown
                          </h3>
                          <span className="text-[11px] font-bold text-orange-400 bg-orange-500/10 border border-orange-500/25 px-2 py-0.5 rounded-full">
                            {activeClip.viral_score.overall}/100 Overall Score
                          </span>
                        </div>

                        {/* Breakdown Metrics */}
                        <div className="grid grid-cols-2 gap-4">
                          {[
                            { label: "Hook Strength", val: activeClip.viral_score.hook_strength, color: "bg-orange-500" },
                            { label: "Pacing", val: activeClip.viral_score.pacing, color: "bg-violet-500" },
                            { label: "Emotion", val: activeClip.viral_score.emotion, color: "bg-pink-500" },
                            { label: "Shareability", val: activeClip.viral_score.shareability, color: "bg-emerald-500" },
                          ].map((metric) => (
                            <div key={metric.label} className="space-y-1">
                              <div className="flex justify-between text-[10px] font-medium text-slate-400">
                                <span>{metric.label}</span>
                                <span>{metric.val}%</span>
                              </div>
                              <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                                <div className={`h-full ${metric.color}`} style={{ width: `${metric.val}%` }} />
                              </div>
                            </div>
                          ))}
                        </div>

                        <div className="border-t border-slate-800/80 pt-3">
                          <span className="text-[10px] font-semibold text-slate-400 block mb-1">
                            Virality Reasoning:
                          </span>
                          <p className="text-[11px] text-slate-400 leading-relaxed italic">
                            "{activeClip.viral_score.reasoning}"
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Clip Transcript */}
                    {activeClip.transcript && (
                      <div className="border border-slate-800/80 bg-slate-900/10 rounded-2xl p-5">
                        <h3 className="text-xs font-bold text-slate-300 flex items-center gap-1.5 mb-2.5">
                          <FileText size={12} className="text-jarvis-400" />
                          Clip Transcript
                        </h3>
                        <div className="max-h-[150px] overflow-y-auto custom-scrollbar text-[11px] text-slate-400 leading-relaxed bg-slate-950/20 p-3 rounded-xl border border-slate-800/40">
                          {activeClip.transcript}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center p-12 text-center border border-slate-800/80 rounded-2xl bg-slate-900/10">
                    <Video className="text-slate-700 mb-2" size={32} />
                    <p className="text-xs text-slate-500">Select a clip from the left list to view it.</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
