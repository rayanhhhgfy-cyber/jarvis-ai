import { readFileSync, writeFileSync, readdirSync, existsSync, statSync, mkdirSync } from "fs";
import path from "path";
import { type ToolHandler } from "./types";

export const readFile: ToolHandler = async (args) => {
  const filepath = args.path as string;
  const maxSize = (args.maxSize as number) || 102400;

  if (!filepath || typeof filepath !== "string") {
    return { success: false, error: "path is required" };
  }

  try {
    if (!existsSync(filepath)) {
      return { success: false, error: `File not found: ${filepath}` };
    }
    const stats = statSync(filepath);
    if (stats.size > maxSize) {
      return {
        success: false,
        error: `File too large (${stats.size} bytes). Max allowed: ${maxSize} bytes. Use head/tail or read with offset.`,
      };
    }
    const content = readFileSync(filepath, "utf-8");
    return { success: true, data: { content, size: stats.size, path: filepath } };
  } catch (err) {
    return { success: false, error: (err as Error).message };
  }
};

export const writeFile: ToolHandler = async (args) => {
  const filepath = args.path as string;
  const content = args.content as string;

  if (!filepath || typeof filepath !== "string") {
    return { success: false, error: "path is required" };
  }
  if (content === undefined || content === null) {
    return { success: false, error: "content is required" };
  }

  try {
    const dir = path.dirname(filepath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
    writeFileSync(filepath, String(content), "utf-8");
    return { success: true, data: { path: filepath, size: String(content).length } };
  } catch (err) {
    return { success: false, error: (err as Error).message };
  }
};

export const listDirectory: ToolHandler = async (args) => {
  const dirpath = args.path as string;

  if (!dirpath || typeof dirpath !== "string") {
    return { success: false, error: "path is required" };
  }

  try {
    if (!existsSync(dirpath)) {
      return { success: false, error: `Directory not found: ${dirpath}` };
    }
    const entries = readdirSync(dirpath, { withFileTypes: true });
    const files = entries.map(e => ({
      name: e.name,
      type: e.isDirectory() ? "directory" : e.isFile() ? "file" : "other",
      size: e.isFile() ? statSync(path.join(dirpath, e.name)).size : 0,
    }));
    return { success: true, data: { path: dirpath, files } };
  } catch (err) {
    return { success: false, error: (err as Error).message };
  }
};
