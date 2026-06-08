"use client";

import React, { useMemo, useState } from "react";
import {
  File,
  Folder,
  FolderOpen,
  FileCode,
  FileJson,
  FileText,
  FileType,
  ChevronRight,
  ChevronDown,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TreeNode {
  name: string;
  path: string;          // full relative path
  isDir: boolean;
  children: TreeNode[];
}

interface FileTreeProps {
  files: string[];        // flat list of relative paths
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode[] = [];

  for (const fullPath of paths) {
    const parts = fullPath.split("/");
    let siblings = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      const existing = siblings.find((n) => n.name === part);

      if (existing) {
        siblings = existing.children;
      } else {
        const node: TreeNode = {
          name: part,
          path: parts.slice(0, i + 1).join("/"),
          isDir: !isLast,
          children: [],
        };
        siblings.push(node);
        siblings = node.children;
      }
    }
  }

  // Sort: directories first, then alphabetical
  const sortNodes = (nodes: TreeNode[]): TreeNode[] =>
    nodes
      .sort((a, b) => {
        if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
        return a.name.localeCompare(b.name);
      })
      .map((n) => ({ ...n, children: sortNodes(n.children) }));

  return sortNodes(root);
}

function getFileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "tsx":
    case "ts":
    case "jsx":
    case "js":
      return <FileCode size={14} className="text-sky-400" />;
    case "json":
      return <FileJson size={14} className="text-amber-400" />;
    case "css":
    case "scss":
      return <FileType size={14} className="text-purple-400" />;
    case "md":
    case "txt":
      return <FileText size={14} className="text-slate-400" />;
    default:
      return <File size={14} className="text-slate-500" />;
  }
}

/* ------------------------------------------------------------------ */
/*  TreeItem                                                           */
/* ------------------------------------------------------------------ */

function TreeItem({
  node,
  depth,
  selectedFile,
  expanded,
  onToggle,
  onSelectFile,
}: {
  node: TreeNode;
  depth: number;
  selectedFile: string | null;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onSelectFile: (path: string) => void;
}) {
  const isOpen = expanded.has(node.path);
  const isActive = selectedFile === node.path;

  return (
    <>
      <button
        onClick={() => (node.isDir ? onToggle(node.path) : onSelectFile(node.path))}
        className={`group flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-[13px] transition-colors select-none ${
          isActive
            ? "bg-jarvis-500/15 text-jarvis-300"
            : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
        }`}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
      >
        {node.isDir ? (
          <>
            {isOpen ? (
              <ChevronDown size={12} className="shrink-0 text-slate-500" />
            ) : (
              <ChevronRight size={12} className="shrink-0 text-slate-500" />
            )}
            {isOpen ? (
              <FolderOpen size={14} className="shrink-0 text-jarvis-400" />
            ) : (
              <Folder size={14} className="shrink-0 text-jarvis-500" />
            )}
          </>
        ) : (
          <>
            <span className="w-3 shrink-0" />
            {getFileIcon(node.name)}
          </>
        )}
        <span className="truncate">{node.name}</span>
      </button>

      {node.isDir &&
        isOpen &&
        node.children.map((child) => (
          <TreeItem
            key={child.path}
            node={child}
            depth={depth + 1}
            selectedFile={selectedFile}
            expanded={expanded}
            onToggle={onToggle}
            onSelectFile={onSelectFile}
          />
        ))}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  FileTree (export)                                                  */
/* ------------------------------------------------------------------ */

export default function FileTree({ files, selectedFile, onSelectFile }: FileTreeProps) {
  const tree = useMemo(() => buildTree(files), [files]);

  // Auto-expand all directories initially
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const dirs = new Set<string>();
    for (const f of files) {
      const parts = f.split("/");
      for (let i = 1; i < parts.length; i++) {
        dirs.add(parts.slice(0, i).join("/"));
      }
    }
    return dirs;
  });

  const toggle = (path: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });

  if (files.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-slate-600 p-4 text-center">
        No files generated yet.
        <br />
        Enter a prompt to build.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0.5 overflow-y-auto p-2 custom-scrollbar">
      {tree.map((node) => (
        <TreeItem
          key={node.path}
          node={node}
          depth={0}
          selectedFile={selectedFile}
          expanded={expanded}
          onToggle={toggle}
          onSelectFile={onSelectFile}
        />
      ))}
    </div>
  );
}
