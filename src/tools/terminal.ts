import { spawn } from "child_process";
import { type ToolHandler } from "./types";

export const runCommand: ToolHandler = async (args, ctx) => {
  const command = args.command as string;
  const timeout = (args.timeout as number) || ctx.configManager.get<number>("safety.commandTimeout") || 30000;
  const cwd = args.cwd as string | undefined;

  if (!command || typeof command !== "string") {
    return { success: false, error: "command is required" };
  }

  return new Promise((resolve) => {
    const isWin = process.platform === "win32";
    const child = spawn(isWin ? "cmd.exe" : "/bin/sh", [isWin ? "/c" : "-c", command], {
      cwd,
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";
    const maxOutput = ctx.configManager.get<number>("safety.outputTruncationSize") || 10240;

    const timer = setTimeout(() => {
      child.kill();
      resolve({ success: false, error: `Command timed out after ${timeout}ms` });
    }, timeout);

    child.stdout?.on("data", (data: Buffer) => {
      stdout += data.toString();
      if (stdout.length > maxOutput) {
        stdout = stdout.slice(0, maxOutput) + "\n... [truncated]";
        child.kill();
      }
    });

    child.stderr?.on("data", (data: Buffer) => {
      stderr += data.toString();
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({
        success: code === 0,
        output: stdout,
        data: { exitCode: code, stderr: stderr.slice(0, maxOutput) },
      });
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ success: false, error: err.message });
    });
  });
};
