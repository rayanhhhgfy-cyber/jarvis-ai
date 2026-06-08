import { execSync } from "child_process";
import { type ToolHandler } from "./types";

function powershell(script: string): string {
  const encoded = Buffer.from(script, "utf16le").toString("base64");
  return execSync(`powershell.exe -NoProfile -EncodedCommand ${encoded}`, {
    timeout: 10000,
    windowsHide: true,
  }).toString().trim();
}

export const getClipboard: ToolHandler = async (_args, _ctx) => {
  try {
    const content = powershell("Get-Clipboard");
    return { success: true, data: { content } };
  } catch (err) {
    return { success: false, error: `Failed to read clipboard: ${(err as Error).message}` };
  }
};

export const setClipboard: ToolHandler = async (args, _ctx) => {
  const text = args.text as string;
  if (text === undefined || text === null) {
    return { success: false, error: "text is required" };
  }
  try {
    const escaped = text.replace(/'/g, "''");
    powershell(`Set-Clipboard -Value '${escaped}'`);
    return { success: true, data: { length: text.length } };
  } catch (err) {
    return { success: false, error: `Failed to set clipboard: ${(err as Error).message}` };
  }
};
