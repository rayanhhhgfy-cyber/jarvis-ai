"use client";

import React, { useCallback, useRef, useState } from "react";
import Editor, { OnMount, OnChange } from "@monaco-editor/react";
import { Save, Loader2, Check, AlertCircle } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface MonacoEditorProps {
  projectId: string;
  filePath: string | null;
  content: string;
  onContentChange: (path: string, newContent: string) => void;
  onSave: (path: string, content: string) => Promise<boolean>;
}

/* ------------------------------------------------------------------ */
/*  Language from extension                                            */
/* ------------------------------------------------------------------ */

function inferLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    css: "css",
    scss: "scss",
    html: "html",
    md: "markdown",
    py: "python",
    yaml: "yaml",
    yml: "yaml",
    toml: "ini",
    sql: "sql",
    sh: "shell",
    bash: "shell",
    dockerfile: "dockerfile",
    gitignore: "plaintext",
    env: "plaintext",
  };
  return map[ext] || "plaintext";
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function MonacoEditorWrapper({
  projectId,
  filePath,
  content,
  onContentChange,
  onSave,
}: MonacoEditorProps) {
  const editorRef = useRef<any>(null);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");
  const [dirty, setDirty] = useState(false);

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;

    // Custom JARVIS theme
    monaco.editor.defineTheme("jarvis-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "comment", foreground: "6b7280", fontStyle: "italic" },
        { token: "keyword", foreground: "38bdf8" },
        { token: "string", foreground: "34d399" },
        { token: "number", foreground: "fbbf24" },
        { token: "type", foreground: "a78bfa" },
        { token: "function", foreground: "60a5fa" },
      ],
      colors: {
        "editor.background": "#0b1120",
        "editor.foreground": "#e2e8f0",
        "editor.lineHighlightBackground": "#1e293b",
        "editor.selectionBackground": "#0ea5e930",
        "editorCursor.foreground": "#38bdf8",
        "editorLineNumber.foreground": "#475569",
        "editorLineNumber.activeForeground": "#94a3b8",
        "editorIndentGuide.background": "#1e293b",
        "editorIndentGuide.activeBackground": "#334155",
        "editor.selectionHighlightBackground": "#0ea5e915",
        "editorBracketMatch.background": "#0ea5e920",
        "editorBracketMatch.border": "#0ea5e950",
        "editorWidget.background": "#0f172a",
        "editorWidget.border": "#1e293b",
        "input.background": "#0f172a",
        "dropdown.background": "#0f172a",
        "list.activeSelectionBackground": "#0ea5e920",
        "list.hoverBackground": "#1e293b",
        "minimap.background": "#0b1120",
      },
    });
    monaco.editor.setTheme("jarvis-dark");

    // Ctrl+S / Cmd+S shortcut
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSave();
    });
  };

  const handleChange: OnChange = (value) => {
    if (!filePath || value === undefined) return;
    setDirty(true);
    setSaveStatus("idle");
    onContentChange(filePath, value);
  };

  const handleSave = useCallback(async () => {
    if (!filePath || !editorRef.current) return;
    setSaving(true);
    try {
      const currentValue = editorRef.current.getValue();
      const ok = await onSave(filePath, currentValue);
      setSaveStatus(ok ? "success" : "error");
      if (ok) setDirty(false);
    } catch {
      setSaveStatus("error");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveStatus("idle"), 2500);
    }
  }, [filePath, onSave]);

  /* ---- empty state ---- */
  if (!filePath) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4 opacity-20">📝</div>
          <p className="text-sm text-slate-500">Select a file to begin editing</p>
          <p className="text-[11px] text-slate-700 mt-1">
            Or generate a project from the prompt panel
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex items-center justify-between border-b border-slate-800/80 bg-slate-900/40 px-3 py-1.5">
        <div className="flex items-center gap-2">
          <span className="rounded bg-slate-800/60 px-2 py-0.5 text-[11px] font-mono text-slate-400">
            {filePath}
          </span>
          {dirty && (
            <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" title="Unsaved changes" />
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={saving || !dirty}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium transition-all ${
            dirty
              ? "bg-jarvis-500/20 text-jarvis-300 hover:bg-jarvis-500/30 border border-jarvis-500/30"
              : "text-slate-600 cursor-default"
          }`}
        >
          {saving ? (
            <Loader2 size={12} className="animate-spin" />
          ) : saveStatus === "success" ? (
            <Check size={12} className="text-emerald-400" />
          ) : saveStatus === "error" ? (
            <AlertCircle size={12} className="text-red-400" />
          ) : (
            <Save size={12} />
          )}
          {saving ? "Saving..." : saveStatus === "success" ? "Saved" : "Save"}
        </button>
      </div>

      {/* Editor */}
      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          language={inferLanguage(filePath)}
          value={content}
          onMount={handleMount}
          onChange={handleChange}
          loading={
            <div className="flex h-full items-center justify-center">
              <Loader2 className="animate-spin text-jarvis-400" size={24} />
            </div>
          }
          options={{
            fontSize: 13,
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
            fontLigatures: true,
            minimap: { enabled: true, side: "right", size: "proportional" },
            scrollBeyondLastLine: false,
            smoothScrolling: true,
            cursorBlinking: "smooth",
            cursorSmoothCaretAnimation: "on",
            renderWhitespace: "selection",
            bracketPairColorization: { enabled: true },
            padding: { top: 12 },
            lineNumbers: "on",
            glyphMargin: false,
            folding: true,
            wordWrap: "on",
            automaticLayout: true,
            tabSize: 2,
          }}
        />
      </div>
    </div>
  );
}
