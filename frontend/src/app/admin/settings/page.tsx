"use client";

import { useState } from "react";
import { updateSettings } from "@/lib/api";

interface SettingConfig {
  key: string;
  label: string;
  description: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  format: (v: number) => string;
  apiKey: string;
}

const SETTINGS: SettingConfig[] = [
  {
    key: "kelly_multiplier",
    label: "Kelly Multiplier",
    description: "Fraction of Kelly criterion to use for stake sizing (0.25 = quarter Kelly)",
    min: 0.05,
    max: 1.0,
    step: 0.05,
    defaultValue: 0.25,
    format: (v) => v.toFixed(2),
    apiKey: "kelly_multiplier",
  },
  {
    key: "min_confidence",
    label: "Min Confidence",
    description: "Minimum confidence score (0-100) for a bet to qualify as a value bet",
    min: 30,
    max: 90,
    step: 5,
    defaultValue: 60,
    format: (v) => `${v}%`,
    apiKey: "min_confidence",
  },
  {
    key: "min_edge",
    label: "Min Edge",
    description: "Minimum edge (model probability - implied probability) for value bet detection",
    min: 0.0,
    max: 0.15,
    step: 0.005,
    defaultValue: 0.02,
    format: (v) => `${(v * 100).toFixed(1)}%`,
    apiKey: "min_edge",
  },
  {
    key: "odds_min",
    label: "Odds Min",
    description: "Minimum acceptable odds for value bets",
    min: 1.05,
    max: 2.0,
    step: 0.05,
    defaultValue: 1.2,
    format: (v) => v.toFixed(2),
    apiKey: "odds_min",
  },
  {
    key: "odds_max",
    label: "Odds Max",
    description: "Maximum acceptable odds for value bets",
    min: 1.5,
    max: 10.0,
    step: 0.5,
    defaultValue: 2.5,
    format: (v) => v.toFixed(1),
    apiKey: "odds_max",
  },
];

export default function SettingsPage() {
  const [values, setValues] = useState<Record<string, number>>(() => {
    const initial: Record<string, number> = {};
    SETTINGS.forEach((s) => {
      initial[s.key] = s.defaultValue;
    });
    return initial;
  });
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);

  function handleChange(key: string, value: number) {
    setValues((prev) => ({ ...prev, [key]: value }));
    setStatus(null);
  }

  async function handleSave() {
    setSaving(true);
    setStatus(null);
    try {
      const payload: Record<string, number> = {};
      SETTINGS.forEach((s) => {
        payload[s.apiKey] = values[s.key];
      });
      await updateSettings(payload);
      setStatus({ type: "success", message: "Settings saved successfully (runtime only)" });
    } catch (err: unknown) {
      setStatus({
        type: "error",
        message: err instanceof Error ? err.message : "Failed to save settings",
      });
    } finally {
      setSaving(false);
    }
  }

  function handleReset() {
    const initial: Record<string, number> = {};
    SETTINGS.forEach((s) => {
      initial[s.key] = s.defaultValue;
    });
    setValues(initial);
    setStatus(null);
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-gray-500 text-sm mt-1">
          Model weights and thresholds (changes are runtime only, reset on restart)
        </p>
      </div>

      {status && (
        <div
          className={`text-sm px-4 py-3 rounded-lg mb-6 ${
            status.type === "success"
              ? "bg-accent-green/10 border border-accent-green/20 text-accent-green"
              : "bg-accent-red/10 border border-accent-red/20 text-accent-red"
          }`}
        >
          {status.message}
        </div>
      )}

      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-brand-border">
          <h2 className="text-lg font-semibold text-white">Model Parameters</h2>
        </div>

        <div className="divide-y divide-brand-border">
          {SETTINGS.map((setting) => (
            <div key={setting.key} className="px-6 py-5">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <label className="text-sm font-medium text-white">{setting.label}</label>
                  <p className="text-xs text-gray-500 mt-0.5">{setting.description}</p>
                </div>
                <span className="text-lg font-mono font-bold text-accent-green min-w-[80px] text-right">
                  {setting.format(values[setting.key])}
                </span>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-xs text-gray-600 w-12 text-right">
                  {setting.format(setting.min)}
                </span>
                <input
                  type="range"
                  min={setting.min}
                  max={setting.max}
                  step={setting.step}
                  value={values[setting.key]}
                  onChange={(e) => handleChange(setting.key, parseFloat(e.target.value))}
                  className="flex-1 h-2 bg-brand-bg rounded-full appearance-none cursor-pointer accent-accent-green"
                />
                <span className="text-xs text-gray-600 w-12">
                  {setting.format(setting.max)}
                </span>
              </div>
            </div>
          ))}
        </div>

        <div className="px-6 py-4 border-t border-brand-border flex items-center justify-between">
          <button
            onClick={handleReset}
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            Reset to defaults
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-6 py-2.5 bg-accent-green hover:bg-accent-green/90 disabled:opacity-50 text-white font-medium text-sm rounded-lg transition-colors"
          >
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </div>
      </div>
    </div>
  );
}
