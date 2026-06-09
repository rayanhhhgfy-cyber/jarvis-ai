"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, Save, Power, MessageSquarePlus, Lightbulb } from "lucide-react";

type SettingsState = {
  persona: string;
  custom_instructions_a: string;
  custom_instructions_b: string;
  custom_suggestions: string;
  start_on_wakeup: boolean;
  model: string;
};

const personaEmojis: Record<string, string> = {
  teenager: "T",
  adult: "A",
  old_man: "O",
  arab: "Ar",
  western: "W",
};

const personaDescriptions: Record<string, string> = {
  teenager: "Casual, modern slang, pop culture references, short energetic responses",
  adult: "Professional, balanced tone, detailed explanations, corporate context",
  old_man: "Traditional, formal, respectful, uses older idioms",
  arab: "Arabic cultural references, formal Arabic greetings, mixed EN/AR",
  western: "Straightforward, direct, neutral, concise",
};

const personaLabels: Record<string, string> = {
  teenager: "Teenager",
  adult: "Adult",
  old_man: "Old Man",
  arab: "Arab",
  western: "Western",
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsState>({
    persona: "adult",
    custom_instructions_a: "",
    custom_instructions_b: "",
    custom_suggestions: "",
    start_on_wakeup: false,
    model: "openrouter/auto",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/settings/default");
      if (!res.ok) throw new Error(`Failed to load: ${res.status}`);
      const data = await res.json();
      setSettings({
        persona: data.persona || "adult",
        custom_instructions_a: data.custom_instructions_a || "",
        custom_instructions_b: data.custom_instructions_b || "",
        custom_suggestions: data.custom_suggestions || "",
        start_on_wakeup: data.start_on_wakeup || false,
        model: data.model || "openrouter/auto",
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const saveSettings = useCallback(async () => {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const res = await fetch("/api/settings/default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (!res.ok) throw new Error(`Failed to save: ${res.status}`);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }, [settings]);

  const updatePersona = (id: string) => {
    setSettings((prev) => ({ ...prev, persona: id }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="animate-spin text-jarvis-400" size={32} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="mt-1 text-sm text-slate-400">
          Configure how JARVIS speaks to you, what it knows about you, and system behavior.
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-700 bg-rose-900/20 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {/* Start on Wake Up Toggle */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10">
              <Power size={20} className="text-emerald-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Start on Wake Up</h2>
              <p className="text-sm text-slate-400">
                Automatically start the JARVIS backend, frontend, and open the UI when your computer boots.
              </p>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={settings.start_on_wakeup}
            onClick={async () => {
              const next = !settings.start_on_wakeup;
              setSettings((prev) => ({ ...prev, start_on_wakeup: next }));
              try {
                await fetch("/api/settings/default", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ ...settings, start_on_wakeup: next }),
                });
              } catch (e) {
                setSettings((prev) => ({ ...prev, start_on_wakeup: !next }));
              }
            }}
            className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors ${
              settings.start_on_wakeup
                ? "bg-emerald-500"
                : "bg-slate-700"
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition-transform ${
                settings.start_on_wakeup ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>
        {settings.start_on_wakeup && (
          <div className="mt-3 rounded-lg border border-emerald-800/30 bg-emerald-900/10 px-3 py-2 text-xs text-emerald-400">
            ✓ JARVIS will start automatically when you log into Windows. A startup script will be placed in your Windows Startup folder.
          </div>
        )}
      </section>

      {/* Voice / Always Listening */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
        <h2 className="text-lg font-semibold text-white mb-1">Always Listening</h2>
        <p className="text-sm text-slate-400 mb-4">
          When enabled, Jarvis listens for the wake word{" "}
          <span className="text-jarvis-300 font-mono text-xs bg-slate-800/60 px-1.5 py-0.5 rounded">
            &quot;wake up jarvis&quot;
          </span>{" "}
          through your microphone. When detected, Jarvis will bring this window to front and respond.
        </p>
      </section>

      {/* Persona Selector */}
      <section>
        <h2 className="mb-3 text-lg font-semibold text-white">Persona</h2>
        <p className="mb-4 text-sm text-slate-400">
          Choose the personality JARVIS uses when speaking to you.
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {Object.keys(personaLabels).map((id) => {
            const selected = settings.persona === id;
            return (
              <button
                key={id}
                onClick={() => updatePersona(id)}
                className={`group relative flex flex-col items-center gap-2 rounded-xl border p-4 text-center transition-all ${
                  selected
                    ? "border-jarvis-500 bg-jarvis-500/10 shadow-[0_0_16px_rgba(14,165,233,0.15)]"
                    : "border-slate-800 bg-slate-900/50 hover:border-slate-600"
                }`}
              >
                {selected && (
                  <span className="absolute right-2 top-2 text-jarvis-400">
                    <Check size={16} />
                  </span>
                )}
                <span className="text-3xl">{personaEmojis[id]}</span>
                <span
                  className={`text-sm font-medium ${
                    selected ? "text-jarvis-300" : "text-slate-300"
                  }`}
                >
                  {personaLabels[id]}
                </span>
                <span className="text-xs text-slate-500">
                  {personaDescriptions[id]}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      {/* Model Selector */}
      <section>
        <h2 className="mb-3 text-lg font-semibold text-white">Reasoning Model</h2>
        <p className="mb-4 text-sm text-slate-400">
          Select the AI model JARVIS uses for reasoning and responses.
        </p>
        <div className="relative inline-block">
          <select
            disabled
            value={settings.model}
            className="appearance-none rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 pr-10 text-sm text-slate-400 outline-none cursor-not-allowed"
          >
            <option value="openrouter/auto">openrouter/auto (auto-routes)</option>
            <option value="meta-llama/llama-3-8b-instruct">Llama 3 8B</option>
            <option value="gryphe/mythomax-l2-13b">MythoMax 13B</option>
          </select>
          <span className="ml-3 inline-flex items-center rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-400">
            Coming Soon
          </span>
        </div>
      </section>

      {/* Custom Instructions */}
      <section className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold text-white">
            Custom Instructions
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Tell JARVIS about yourself and how you want to be addressed.
          </p>
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-300">
            What should JARVIS know about you to provide better responses?
          </label>
          <p className="mb-2 text-xs text-slate-500">
            Your background, role, skills, preferences, and context.
          </p>
          <textarea
            value={settings.custom_instructions_a}
            onChange={(e) =>
              setSettings((prev) => ({
                ...prev,
                custom_instructions_a: e.target.value,
              }))
            }
            rows={5}
            placeholder="E.g., I'm a software engineer who works remotely. I prefer concise technical answers. I use both English and Arabic daily..."
            className="w-full resize-none rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-jarvis-500/50"
          />
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-300">
            How would you like JARVIS to respond?
          </label>
          <p className="mb-2 text-xs text-slate-500">
            Tone, formatting, language blend, response length preferences.
          </p>
          <textarea
            value={settings.custom_instructions_b}
            onChange={(e) =>
              setSettings((prev) => ({
                ...prev,
                custom_instructions_b: e.target.value,
              }))
            }
            rows={5}
            placeholder="E.g., Be direct and avoid fluff. Use bullet points for instructions. Mix Arabic phrases naturally. Keep responses under 3 paragraphs..."
            className="w-full resize-none rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-jarvis-500/50"
          />
        </div>
      </section>

      {/* Custom Suggestions / Rules */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/10">
            <Lightbulb size={20} className="text-amber-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">
              Custom Suggestions &amp; Rules
            </h2>
            <p className="text-sm text-slate-400">
              Give JARVIS specific instructions, rules, or auto-replies to follow at all times.
            </p>
          </div>
        </div>
        <textarea
          value={settings.custom_suggestions}
          onChange={(e) =>
            setSettings((prev) => ({
              ...prev,
              custom_suggestions: e.target.value,
            }))
          }
          rows={6}
          placeholder={`E.g.,\n- If someone asks about my wedding, tell them it is starting real soon.\n- JARVIS can run a full marketing agency on his own.\n- Always greet people by saying "Sir is unavailable but I can help."\n- Prioritize tasks related to my startup over everything else.`}
          className="w-full resize-none rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-jarvis-500/50"
        />
        <div className="rounded-lg border border-amber-800/30 bg-amber-900/10 px-3 py-2 text-xs text-amber-400/80">
          <MessageSquarePlus size={12} className="inline mr-1.5 -mt-0.5" />
          These rules are injected into every JARVIS conversation and are also used by the 24/7 background scraper to find relevant data for you.
        </div>
      </section>

      <div className="flex items-center gap-3">
        <button
          onClick={saveSettings}
          disabled={saving}
          className="flex items-center gap-2 rounded-xl bg-jarvis-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-jarvis-600 disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="animate-spin" size={16} />
          ) : (
            <Save size={16} />
          )}
          {saving ? "Saving…" : "Save Preferences"}
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-sm text-emerald-400">
            <Check size={16} />
            Saved
          </span>
        )}
      </div>
    </div>
  );
}
