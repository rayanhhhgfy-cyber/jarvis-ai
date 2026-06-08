import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import path from "path";
import { DEFAULT_CONFIG, type Config } from "./types";
import { createLogger } from "../utils/logger";

const log = createLogger("config");

export class ConfigManager {
  private config: Config;
  private configPath: string;

  constructor(configPath?: string) {
    this.configPath = configPath || path.resolve(import.meta.dir, "../../config/daemon.json");
    this.config = this.load();
  }

  private load(): Config {
    try {
      if (existsSync(this.configPath)) {
        const raw = readFileSync(this.configPath, "utf-8");
        const parsed = JSON.parse(raw);
        const merged = this.mergeDefaults(parsed);
        log.info("Config loaded from file", { path: this.configPath });
        return merged;
      }
    } catch (err) {
      log.warn("Failed to load config file, using defaults", { error: (err as Error).message });
    }
    return { ...DEFAULT_CONFIG };
  }

  private mergeDefaults(partial: Partial<Config>): Config {
    const merged: Config = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
    this.deepMerge(merged as unknown as Record<string, unknown>, partial as unknown as Record<string, unknown>);
    return merged;
  }

  private deepMerge(target: Record<string, unknown>, source: Record<string, unknown>): void {
    for (const key of Object.keys(source)) {
      if (source[key] && typeof source[key] === "object" && !Array.isArray(source[key])) {
        if (!target[key]) target[key] = {};
        this.deepMerge(target[key] as Record<string, unknown>, source[key] as Record<string, unknown>);
      } else if (source[key] !== undefined) {
        target[key] = source[key];
      }
    }
  }

  get<T = unknown>(key: string): T {
    const keys = key.split(".");
    let value: unknown = this.config;
    for (const k of keys) {
      if (value && typeof value === "object" && k in (value as Record<string, unknown>)) {
        value = (value as Record<string, unknown>)[k];
      } else {
        return undefined as T;
      }
    }
    return value as T;
  }

  set(key: string, value: unknown): void {
    const keys = key.split(".");
    let target: Record<string, unknown> = this.config as unknown as Record<string, unknown>;
    for (let i = 0; i < keys.length - 1; i++) {
      if (!target[keys[i]] || typeof target[keys[i]] !== "object") {
        target[keys[i]] = {};
      }
      target = target[keys[i]] as Record<string, unknown>;
    }
    target[keys[keys.length - 1]] = value;
    this.save();
  }

  getAll(): Config {
    return { ...this.config };
  }

  save(): void {
    try {
      const dir = path.dirname(this.configPath);
      if (!existsSync(dir)) {
        mkdirSync(dir, { recursive: true });
      }
      writeFileSync(this.configPath, JSON.stringify(this.config, null, 2), "utf-8");
      log.info("Config saved", { path: this.configPath });
    } catch (err) {
      log.error("Failed to save config", { error: (err as Error).message });
    }
  }

  reset(): void {
    this.config = { ...DEFAULT_CONFIG };
    this.save();
  }

  reload(): void {
    this.config = this.load();
  }
}
