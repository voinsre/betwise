"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getRetrainLogs,
  getModelStatus,
  triggerRetrain,
  backfillRetrainLogs,
  RetrainLogEntry,
  ModelMeta,
} from "@/lib/api";

/* ─── Constants ─── */

const MARKETS = ["1x2", "ou25", "btts", "htft"];

const MARKET_COLORS: Record<string, string> = {
  "1x2": "bg-blue-500/15 text-blue-400 border-blue-500/25",
  ou25: "bg-purple-500/15 text-purple-400 border-purple-500/25",
  btts: "bg-pink-500/15 text-pink-400 border-pink-500/25",
  htft: "bg-orange-500/15 text-orange-400 border-orange-500/25",
};

const STATUS_STYLES: Record<string, string> = {
  success: "bg-green-500/15 text-green-400 border-green-500/25",
  failed: "bg-red-500/15 text-red-400 border-red-500/25",
  skipped: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  running: "bg-blue-500/15 text-blue-400 border-blue-500/25",
};

/* ─── Helpers ─── */

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function freshnessColor(dateStr: string | undefined): string {
  if (!dateStr) return "text-gray-500";
  const days = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / (1000 * 60 * 60 * 24)
  );
  if (days <= 10) return "text-accent-green";
  if (days <= 20) return "text-accent-amber";
  return "text-accent-red";
}

function freshnessLabel(dateStr: string | undefined): string {
  if (!dateStr) return "Never";
  const days = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / (1000 * 60 * 60 * 24)
  );
  if (days === 0) return "Today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "--";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

/* ─── Component ─── */

export default function RetrainPage() {
  const [logs, setLogs] = useState<RetrainLogEntry[]>([]);
  const [models, setModels] = useState<Record<string, ModelMeta>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retraining, setRetraining] = useState(false);
  const [retrainMsg, setRetrainMsg] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [logRes, modelRes] = await Promise.all([
        getRetrainLogs({ limit: 100 }),
        getModelStatus(),
      ]);
      setLogs(logRes.logs);
      setModels(modelRes.models);
      setError("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchData().finally(() => setLoading(false));
  }, [fetchData]);

  async function handleRetrain() {
    setRetraining(true);
    setRetrainMsg("");
    try {
      const res = await triggerRetrain();
      setRetrainMsg(res.message || "Retrain started");
      // Poll for updates after a delay
      setTimeout(() => fetchData(), 5000);
    } catch (err: unknown) {
      setRetrainMsg(
        err instanceof Error ? err.message : "Failed to trigger retrain"
      );
    } finally {
      setRetraining(false);
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-screen">
        <div className="w-8 h-8 border-2 border-accent-green border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Group logs by retrain run (same started_at timestamp)
  const runs: { date: string; triggered_by: string; markets: RetrainLogEntry[] }[] = [];
  const runMap: Record<string, RetrainLogEntry[]> = {};
  for (const log of logs) {
    const key = log.started_at || "unknown";
    if (!runMap[key]) runMap[key] = [];
    runMap[key].push(log);
  }
  for (const dateKey of Object.keys(runMap)) {
    const entries = runMap[dateKey];
    runs.push({
      date: dateKey,
      triggered_by: entries[0]?.triggered_by || "unknown",
      markets: entries,
    });
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">ML Retrain</h1>
          <p className="text-gray-500 text-sm mt-1">
            XGBoost model training history &amp; current status
          </p>
        </div>
        <button
          onClick={handleRetrain}
          disabled={retraining}
          className="px-4 py-2 bg-accent-green/10 border border-accent-green/25 text-accent-green rounded-lg text-sm font-medium hover:bg-accent-green/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {retraining ? (
            <span className="flex items-center gap-2">
              <span className="w-4 h-4 border-2 border-accent-green border-t-transparent rounded-full animate-spin" />
              Retraining...
            </span>
          ) : (
            "Trigger Retrain"
          )}
        </button>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {retrainMsg && (
        <div className="bg-accent-green/10 border border-accent-green/20 text-accent-green text-sm px-4 py-3 rounded-lg mb-6">
          {retrainMsg}
        </div>
      )}

      {/* Current Model Status Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {MARKETS.map((market) => {
          const meta = models[market];
          const retrainDate = meta?.retrain_date;
          const hasRetrain = !!retrainDate;

          return (
            <div
              key={market}
              className="bg-brand-card border border-brand-border rounded-xl p-5"
            >
              <div className="flex items-center justify-between mb-3">
                <span
                  className={`text-xs px-2 py-1 rounded-md font-semibold uppercase border ${
                    MARKET_COLORS[market] ||
                    "bg-gray-500/15 text-gray-400 border-gray-500/25"
                  }`}
                >
                  {market}
                </span>
                <span className={`text-xs ${freshnessColor(retrainDate)}`}>
                  {freshnessLabel(retrainDate)}
                </span>
              </div>

              {hasRetrain ? (
                <>
                  <div className="grid grid-cols-2 gap-3 mb-3">
                    <div>
                      <div className="text-xs text-gray-500 mb-0.5">
                        Accuracy
                      </div>
                      <div className="text-lg font-bold text-white">
                        {meta.accuracy != null
                          ? `${(meta.accuracy * 100).toFixed(1)}%`
                          : "--"}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-gray-500 mb-0.5">
                        Log Loss
                      </div>
                      <div className="text-lg font-bold text-white">
                        {meta.log_loss != null
                          ? meta.log_loss.toFixed(4)
                          : "--"}
                      </div>
                    </div>
                  </div>
                  <div className="text-xs text-gray-500 space-y-0.5">
                    <div>
                      Train: {meta.train_samples?.toLocaleString() ?? "--"}{" "}
                      samples
                    </div>
                    <div>
                      Val: {meta.val_samples?.toLocaleString() ?? "--"} samples
                    </div>
                    {meta.train_range && (
                      <div className="text-gray-600">{meta.train_range}</div>
                    )}
                  </div>
                </>
              ) : (
                <div className="text-sm text-gray-500">
                  {meta?.error || "No retrain data available"}
                  {meta?.train_seasons && (
                    <div className="mt-2 text-xs text-gray-600">
                      Initial training: seasons{" "}
                      {meta.train_seasons.join(", ")}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Retrain History */}
      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-brand-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Retrain History</h2>
          <span className="text-xs text-gray-500">
            {runs.length} run{runs.length !== 1 ? "s" : ""}
          </span>
        </div>

        {logs.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            <p>No retrain history yet. Models are retrained every Monday at 03:00 UTC.</p>
            <button
              onClick={async () => {
                try {
                  const res = await backfillRetrainLogs();
                  if (res.status === "ok") {
                    setRetrainMsg(`Backfilled ${res.inserted} retrain records from model metadata files.`);
                    fetchData();
                  } else {
                    setRetrainMsg(res.message || "Backfill skipped");
                  }
                } catch (err: unknown) {
                  setRetrainMsg(err instanceof Error ? err.message : "Backfill failed");
                }
              }}
              className="mt-3 px-4 py-2 bg-brand-surface border border-brand-border text-gray-300 rounded-lg text-sm hover:bg-brand-card transition-colors"
            >
              Import History from Model Files
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                  <th className="px-6 py-3 text-left">Date</th>
                  <th className="px-4 py-3 text-left">Market</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-right">Accuracy</th>
                  <th className="px-4 py-3 text-right">Log Loss</th>
                  <th className="px-4 py-3 text-right hidden sm:table-cell">
                    Train
                  </th>
                  <th className="px-4 py-3 text-right hidden sm:table-cell">
                    Val
                  </th>
                  <th className="px-4 py-3 text-right hidden md:table-cell">
                    Duration
                  </th>
                  <th className="px-6 py-3 text-left hidden md:table-cell">
                    Trigger
                  </th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => {
                  const isExpanded = expandedId === log.id;
                  return (
                    <LogRow
                      key={log.id}
                      log={log}
                      isExpanded={isExpanded}
                      onToggle={() =>
                        setExpandedId(isExpanded ? null : log.id)
                      }
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── LogRow ─── */

function LogRow({
  log,
  isExpanded,
  onToggle,
}: {
  log: RetrainLogEntry;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const statusStyle =
    STATUS_STYLES[log.status] ||
    "bg-gray-500/15 text-gray-400 border-gray-500/25";
  const hasDetails = log.best_params || log.error_message;

  return (
    <>
      <tr
        className={`border-b border-brand-border/50 transition-colors ${
          hasDetails
            ? "cursor-pointer hover:bg-brand-surface/50"
            : ""
        } ${isExpanded ? "bg-brand-surface/30" : ""}`}
        onClick={hasDetails ? onToggle : undefined}
      >
        <td className="px-6 py-3 text-sm text-gray-400">
          {formatDateTime(log.started_at)}
        </td>
        <td className="px-4 py-3">
          <span
            className={`text-xs px-2 py-0.5 rounded-md uppercase border ${
              MARKET_COLORS[log.market] ||
              "bg-gray-500/15 text-gray-400 border-gray-500/25"
            }`}
          >
            {log.market}
          </span>
        </td>
        <td className="px-4 py-3">
          <span
            className={`text-xs px-2 py-0.5 rounded-md border ${statusStyle}`}
          >
            {log.status}
          </span>
        </td>
        <td className="px-4 py-3 text-right font-mono text-gray-300">
          {log.accuracy != null
            ? `${(log.accuracy * 100).toFixed(1)}%`
            : "--"}
        </td>
        <td className="px-4 py-3 text-right font-mono text-gray-300">
          {log.log_loss != null ? log.log_loss.toFixed(4) : "--"}
        </td>
        <td className="px-4 py-3 text-right font-mono text-gray-300 hidden sm:table-cell">
          {log.train_samples?.toLocaleString() ?? "--"}
        </td>
        <td className="px-4 py-3 text-right font-mono text-gray-300 hidden sm:table-cell">
          {log.val_samples?.toLocaleString() ?? "--"}
        </td>
        <td className="px-4 py-3 text-right font-mono text-gray-300 hidden md:table-cell">
          {formatDuration(log.duration_seconds)}
        </td>
        <td className="px-6 py-3 text-sm text-gray-500 hidden md:table-cell">
          {log.triggered_by}
        </td>
      </tr>

      {isExpanded && hasDetails && (
        <tr className="bg-brand-surface/20">
          <td colSpan={9} className="px-6 py-4">
            <div className="space-y-3 text-sm">
              {log.train_range && (
                <div>
                  <span className="text-gray-500">Train range: </span>
                  <span className="text-gray-300">{log.train_range}</span>
                </div>
              )}
              {log.val_range && (
                <div>
                  <span className="text-gray-500">Val range: </span>
                  <span className="text-gray-300">{log.val_range}</span>
                </div>
              )}
              {log.best_params && (
                <div>
                  <span className="text-gray-500 block mb-1">
                    Best hyperparameters:
                  </span>
                  <div className="bg-brand-bg rounded-lg p-3 font-mono text-xs text-gray-300 overflow-x-auto">
                    {Object.entries(log.best_params).map(([k, v]) => (
                      <div key={k}>
                        <span className="text-gray-500">{k}:</span>{" "}
                        <span className="text-accent-green">
                          {typeof v === "number" ? v.toPrecision(4) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {log.error_message && (
                <div>
                  <span className="text-gray-500">Error: </span>
                  <span className="text-accent-red">{log.error_message}</span>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
