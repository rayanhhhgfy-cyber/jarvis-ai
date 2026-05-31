import { type ToolHandler } from "./types";
import { platform, hostname, totalmem, freemem, cpus, uptime, arch, type } from "os";

export const getSystemInfo: ToolHandler = async () => {
  const mem = {
    total: totalmem(),
    free: freemem(),
    used: totalmem() - freemem(),
  };

  return {
    success: true,
    data: {
      platform: platform(),
      hostname: hostname(),
      arch: arch(),
      osType: type(),
      uptime: uptime(),
      memory: mem,
      cpus: cpus().map(c => ({
        model: c.model,
        speed: c.speed,
        cores: 1,
      })),
      cpuCount: cpus().length,
      nodeVersion: process.version,
      bunVersion: typeof Bun !== "undefined" ? Bun.version : undefined,
      pid: process.pid,
      cwd: process.cwd(),
    },
  };
};
