"use client";

import { useEffect, useState, useCallback } from "react";
import { listGeneratedMedia, deleteMedia, generateImage, generateVideo } from "../../lib/api";
import type { MediaFile } from "../../lib/api";
import { Trash2, Copy, ExternalLink, ImagePlus, Video, RefreshCw, Loader2, X, Check } from "lucide-react";

export default function MediaPage() {
  const [files, setFiles] = useState<MediaFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [showGenerate, setShowGenerate] = useState(false);
  const [genType, setGenType] = useState<"image" | "video">("image");
  const [genPrompt, setGenPrompt] = useState("");
  const [genModel, setGenModel] = useState("");
  const [genSize, setGenSize] = useState("1024x1024");
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const loadFiles = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await listGeneratedMedia();
      setFiles(result);
    } catch (e) {
      setError("Failed to load media");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadFiles(); }, [loadFiles]);

  const handleDelete = async (filename: string) => {
    setDeleting(filename);
    const ok = await deleteMedia(filename);
    if (ok) {
      setFiles((prev) => prev.filter((f) => f.filename !== filename));
    }
    setDeleting(null);
  };

  const handleCopyUrl = async (url: string) => {
    try {
      await navigator.clipboard.writeText(window.location.origin + url);
      setCopied(url);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      // fallback
    }
  };

  const handleGenerate = async () => {
    if (!genPrompt.trim()) return;
    setGenerating(true);
    try {
      if (genType === "image") {
        await generateImage(genPrompt.trim(), genModel || undefined, genSize || undefined);
      } else {
        await generateVideo(genPrompt.trim(), genModel || undefined, 5);
      }
      setGenPrompt("");
      setShowGenerate(false);
      await loadFiles();
    } catch (e: any) {
      setError(e.message || "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const isVideo = (mime: string) => mime.startsWith("video/");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Media Gallery</h1>
          <p className="text-sm text-slate-400 mt-1">
            {files.length} file{files.length !== 1 ? "s" : ""} generated
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadFiles}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors"
          >
            <RefreshCw size={16} />
            Refresh
          </button>
          <button
            onClick={() => setShowGenerate(true)}
            className="flex items-center gap-2 rounded-lg bg-jarvis-500/20 px-4 py-2 text-sm font-medium text-jarvis-300 hover:bg-jarvis-500/30 transition-colors border border-jarvis-500/30"
          >
            <ImagePlus size={16} />
            Generate
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-800/50 bg-red-900/20 px-4 py-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError("")} className="ml-2 underline">Dismiss</button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="animate-spin text-slate-500" size={32} />
        </div>
      ) : files.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-slate-500">
          <ImagePlus size={48} className="mb-4 opacity-40" />
          <p className="text-lg font-medium">No media yet</p>
          <p className="text-sm mt-1">Generated images and videos will appear here.</p>
          <button
            onClick={() => setShowGenerate(true)}
            className="mt-4 rounded-lg bg-jarvis-500/20 px-4 py-2 text-sm text-jarvis-300 hover:bg-jarvis-500/30 transition-colors border border-jarvis-500/30"
          >
            Generate your first media
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {files.map((file) => (
            <div
              key={file.filename}
              className="group relative overflow-hidden rounded-lg border border-slate-800 bg-slate-900/60"
            >
              {isVideo(file.mime_type) ? (
                <video
                  src={file.url}
                  className="h-40 w-full object-cover"
                  muted
                  preload="metadata"
                  onMouseEnter={(e) => e.currentTarget.play()}
                  onMouseLeave={(e) => { e.currentTarget.pause(); e.currentTarget.currentTime = 0; }}
                />
              ) : (
                <img
                  src={file.url}
                  alt={file.filename}
                  className="h-40 w-full object-cover"
                  loading="lazy"
                />
              )}
              <div className="absolute inset-0 flex items-center justify-center gap-2 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => handleCopyUrl(file.url)}
                  className="rounded-full bg-slate-800/80 p-2 text-slate-300 hover:bg-slate-700 transition-colors"
                  title="Copy URL"
                >
                  {copied === file.url ? <Check size={16} className="text-green-400" /> : <Copy size={16} />}
                </button>
                <a
                  href={file.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-full bg-slate-800/80 p-2 text-slate-300 hover:bg-slate-700 transition-colors"
                  title="Open in new tab"
                >
                  <ExternalLink size={16} />
                </a>
                <button
                  onClick={() => handleDelete(file.filename)}
                  disabled={deleting === file.filename}
                  className="rounded-full bg-red-900/60 p-2 text-red-300 hover:bg-red-800/80 transition-colors disabled:opacity-50"
                  title="Delete"
                >
                  {deleting === file.filename ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                </button>
              </div>
              <div className="px-2 py-1.5">
                <p className="truncate text-xs text-slate-400" title={file.filename}>
                  {file.filename}
                </p>
                <p className="text-[10px] text-slate-600">{formatSize(file.size_bytes)}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {showGenerate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-slate-100">Generate Media</h2>
              <button
                onClick={() => setShowGenerate(false)}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex gap-2 mb-4">
              <button
                onClick={() => setGenType("image")}
                className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                  genType === "image"
                    ? "bg-jarvis-500/20 text-jarvis-300 border border-jarvis-500/30"
                    : "bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700"
                }`}
              >
                Image
              </button>
              <button
                onClick={() => setGenType("video")}
                className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                  genType === "video"
                    ? "bg-jarvis-500/20 text-jarvis-300 border border-jarvis-500/30"
                    : "bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700"
                }`}
              >
                Video
              </button>
            </div>

            <textarea
              value={genPrompt}
              onChange={(e) => setGenPrompt(e.target.value)}
              placeholder="Describe what you want to generate..."
              className="w-full rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-jarvis-500/50 focus:outline-none resize-none"
              rows={3}
            />

            {genType === "image" && (
              <div className="flex gap-2 mt-3">
                <select
                  value={genModel}
                  onChange={(e) => setGenModel(e.target.value)}
                  className="flex-1 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm text-slate-300 focus:border-jarvis-500/50 focus:outline-none"
                >
                  <option value="">Default (flux-schnell)</option>
                  <option value="black-forest-labs/flux-schnell">Flux Schnell (fast)</option>
                  <option value="black-forest-labs/flux-pro">Flux Pro (quality)</option>
                  <option value="stabilityai/stable-diffusion-3.5-medium">Stable Diffusion 3.5</option>
                  <option value="openai/dall-e-3">DALL-E 3</option>
                </select>
                <select
                  value={genSize}
                  onChange={(e) => setGenSize(e.target.value)}
                  className="w-28 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm text-slate-300 focus:border-jarvis-500/50 focus:outline-none"
                >
                  <option value="1024x1024">Square</option>
                  <option value="1024x1792">Portrait</option>
                  <option value="1792x1024">Landscape</option>
                </select>
              </div>
            )}

            {genType === "video" && (
              <select
                value={genModel}
                onChange={(e) => setGenModel(e.target.value)}
                className="w-full mt-3 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm text-slate-300 focus:border-jarvis-500/50 focus:outline-none"
              >
                <option value="">Default (luma/ray)</option>
                <option value="luma/ray">Luma Ray (best)</option>
                <option value="minimax/video-01">MiniMax (fast)</option>
                <option value="kuaishou/kling-video">Kling (cinematic)</option>
              </select>
            )}

            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setShowGenerate(false)}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-400 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleGenerate}
                disabled={!genPrompt.trim() || generating}
                className="flex items-center gap-2 rounded-lg bg-jarvis-500/30 px-4 py-2 text-sm font-medium text-jarvis-300 hover:bg-jarvis-500/40 transition-colors disabled:opacity-50 border border-jarvis-500/30"
              >
                {generating ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    {genType === "image" ? <ImagePlus size={16} /> : <Video size={16} />}
                    Generate {genType === "image" ? "Image" : "Video"}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
