#!/usr/bin/env bun
import { Daemon } from "./daemon/index";
import { createLogger } from "./utils/logger";

const log = createLogger("main");

async function main() {
  const args = process.argv.slice(2);
  const options: { configPath?: string; noLocalTools?: boolean } = {};

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--config":
      case "-c":
        options.configPath = args[++i];
        break;
      case "--no-local-tools":
        options.noLocalTools = true;
        break;
      case "--help":
      case "-h":
        console.log(`
Jarvis Omega - Always-on Autonomous AI Daemon

Usage: bun run index.ts [options]

Options:
  -c, --config <path>    Path to config file
  --no-local-tools       Disable local tool execution
  -h, --help             Show this help message

Commands:
  start                  Start the daemon (default)
        `);
        process.exit(0);
        break;
    }
  }

  const daemon = new Daemon(options);

  // Handle graceful shutdown
  const shutdown = async () => {
    log.info("Shutdown signal received");
    await daemon.stop();
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("uncaughtException", (err) => {
    log.error("Uncaught exception", { error: err.message, stack: err.stack });
  });
  process.on("unhandledRejection", (reason) => {
    log.error("Unhandled rejection", { reason: String(reason) });
  });

  try {
    await daemon.start();
    // Keep running
    await new Promise(() => {});
  } catch (err) {
    log.error("Failed to start daemon", { error: (err as Error).message });
    process.exit(1);
  }
}

main();
