"use client";

import { useEffect, useState, useCallback } from "react";
import { getAccuracy } from "@/lib/api";

/* ─── Types ─── */

interface AccuracyRow {
  date: string;
  market: string;
  league_id: number | null;
  total_predictions: number;
  correct_predictions: number;
  accuracy_pct: number;
  avg_edge: number;
  avg_confidence: number;
  total_staked: number;
  total_returned: number;
  profit_loss: number;
  roi_pct: number;
}

interface MarketSummary {
  total_predictions: number;
  correct_predictions: number;
  accuracy_pct: number;
  avg_edge: number;
  avg_confidence: number;
  total_staked: number;
  total_returned: number;
  profit_loss: number;
  roi_pct: number;
}

interface AccuracyData {
  accuracy: AccuracyRow[];
  summary_7d: Record<string, MarketSummary>;
  summary_30d: Record<string, MarketSummary>;
  summary_90d: Record<string, MarketSummary>;
  summary_all: Record<string, MarketSummary>;
  date_range: { earliest: string | null; latest: string | null; total_days: number };
}

type RangeKey = "30d" | "90d" | "all";

/* ─── Constants ─── */

const MARKETS = ["1x2", "ou25", "btts", "dc", "htft"];

const MARKET_COLORS: Record<string, string> = {
  "1x2": "bg-blue-500/15 text-blue-400 border-blue-500/25",
  ou25: "bg-purple-500/15 text-purple-400 border-purple-500/25",
  btts: "bg-pink-500/15 text-pink-400 border-pink-500/25",
  dc: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25",
  htft: "bg-orange-500/15 text-orange-400 border-orange-500/25",
};

const MARKET_BAR_COLORS: Record<string, string> = {
  "1x2": "bg-blue-500",
  ou25: "bg-purple-500",
  btts: "bg-pink-500",
  dc: "bg-cyan-500",
  htft: "bg-orange-500",
};

// Market-aware accuracy thresholds: [green_min, amber_min]
// Based on random baselines: 1x2=33%, ou25/btts=50%, dc=66%, htft=11%
const ACCURACY_THRESHOLDS: Record<string, [number, number]> = {
  "1x2": [45, 33],
  ou25: [60, 50],
  btts: [60, 50],
  dc: [75, 66],
  htft: [20, 11],
};

const RANGE_LABELS: Record<RangeKey, string> = {
  "30d": "30D",
  "90d": "90D",
  all: "All-time",
};

/* ─── Helpers ─── */

function accuracyColor(market: string, pct: number): string {
  const [green, amber] = ACCURACY_THRESHOLDS[market] || [60, 50];
  if (pct >= green) return "text-accent-green";
  if (pct >= amber) return "text-accent-amber";
  return "text-accent-red";
}

function confidenceColor(c: number): string {
  if (c >= 80) return "text-accent-green";
  if (c >= 65) return "text-accent-amber";
  return "text-gray-400";
}

function plColor(v: number): string {
  return v >= 0 ? "text-accent-green" : "text-accent-red";
}

function formatPL(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
}

function computeKPIs(summary: Record<string, MarketSummary>) {
  let totalPreds = 0,
    totalCorrect = 0,
    totalStaked = 0,
    totalPL = 0;
  for (const ms of Object.values(summary)) {
    totalPreds += ms.total_predictions;
    totalCorrect += ms.correct_predictions;
    totalStaked += ms.total_staked;
    totalPL += ms.profit_loss;
  }
  return {
    totalPreds,
    overallAccuracy: totalPreds > 0 ? (totalCorrect / totalPreds) * 100 : 0,
    totalPL,
    overallROI: totalStaked > 0 ? (totalPL / totalStaked) * 100 : 0,
  };
}

/* ─── Component ─── */

export default function AccuracyPage() {
  const [data, setData] = useState<AccuracyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Per-market summary range
  const [summaryRange, setSummaryRange] = useState<RangeKey>("30d");

  // Daily breakdown controls
  const [selectedMarket, setSelectedMarket] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState("");

  const fetchData = useCallback(async (dateFilter?: string) => {
    try {
      const params = dateFilter ? { date: dateFilter } : undefined;
      const res = await getAccuracy(params);
      setData(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchData().finally(() => setLoading(false));
  }, [fetchData]);

  // Refetch when date filter changes
  useEffect(() => {
    if (!data) return; // skip initial
    fetchData(filterDate || undefined);
  }, [filterDate, fetchData]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-screen">
        <div className="w-8 h-8 border-2 border-accent-green border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-8">
        {error && (
          <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg">
            {error}
          </div>
        )}
      </div>
    );
  }

  // Active summary based on range selector (defensive fallbacks for partial API responses)
  const empty: Record<string, MarketSummary> = {};
  const summaryMap: Record<RangeKey, Record<string, MarketSummary>> = {
    "30d": data.summary_30d || empty,
    "90d": data.summary_90d || empty,
    all: data.summary_all || empty,
  };
  const activeSummary = summaryMap[summaryRange];
  const kpis = computeKPIs(data.summary_30d || empty);

  // Daily breakdown: aggregate by market when no date filter, show per-date rows when filtered
  const dailyRows = data.accuracy || [];
  const showPerDate = !!filterDate;

  const aggregatedByMarket = !showPerDate
    ? MARKETS.map((market) => {
        const rows = dailyRows.filter((r) => r.market === market);
        if (rows.length === 0) return null;
        const totalPreds = rows.reduce((s, r) => s + r.total_predictions, 0);
        const totalCorrect = rows.reduce((s, r) => s + r.correct_predictions, 0);
        const totalStaked = rows.reduce((s, r) => s + (r.total_staked ?? 0), 0);
        const totalReturned = rows.reduce((s, r) => s + (r.total_returned ?? 0), 0);
        const pl = totalReturned - totalStaked;
        return {
          market,
          total_predictions: totalPreds,
          correct_predictions: totalCorrect,
          accuracy_pct: totalPreds > 0 ? (totalCorrect / totalPreds) * 100 : 0,
          avg_edge: totalPreds > 0 ? rows.reduce((s, r) => s + r.avg_edge * r.total_predictions, 0) / totalPreds : 0,
          avg_confidence: totalPreds > 0 ? Math.round(rows.reduce((s, r) => s + r.avg_confidence * r.total_predictions, 0) / totalPreds) : 0,
          total_staked: totalStaked,
          total_returned: totalReturned,
          profit_loss: pl,
          roi_pct: totalStaked > 0 ? (pl / totalStaked) * 100 : 0,
          date_range: `${rows[rows.length - 1].date} — ${rows[0].date}`,
        };
      }).filter(Boolean) as Array<{
        market: string; total_predictions: number; correct_predictions: number;
        accuracy_pct: number; avg_edge: number; avg_confidence: number;
        total_staked: number; total_returned: number; profit_loss: number;
        roi_pct: number; date_range: string;
      }>
    : [];

  const filteredDaily = showPerDate
    ? (selectedMarket ? dailyRows.filter((r) => r.market === selectedMarket) : dailyRows)
    : [];

  const filteredAggregated = selectedMarket
    ? aggregatedByMarket.filter((r) => r.market === selectedMarket)
    : aggregatedByMarket;

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Model Accuracy</h1>
        <p className="text-gray-500 text-sm mt-1">
          Prediction performance &amp; profitability tracking
        </p>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {/* KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <SummaryCard
          label="Total Predictions"
          value={kpis.totalPreds.toLocaleString()}
          icon="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"
        />
        <SummaryCard
          label="Overall Accuracy"
          value={kpis.overallAccuracy.toFixed(1)}
          suffix="%"
          accent={kpis.overallAccuracy >= 50 ? "green" : kpis.overallAccuracy >= 40 ? "amber" : "red"}
          icon="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
        <SummaryCard
          label="30d P&L"
          value={formatPL(kpis.totalPL)}
          suffix="u"
          accent={kpis.totalPL >= 0 ? "green" : "red"}
          icon="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
        <SummaryCard
          label="30d ROI"
          value={`${kpis.overallROI >= 0 ? "+" : ""}${kpis.overallROI.toFixed(1)}`}
          suffix="%"
          accent={kpis.overallROI >= 0 ? "green" : "red"}
          icon="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941"
        />
      </div>

      {/* Per-Market Summary */}
      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-brand-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Per-Market Summary</h2>
          <div className="flex gap-1 bg-brand-surface rounded-lg p-1">
            {(["30d", "90d", "all"] as RangeKey[]).map((range) => (
              <button
                key={range}
                onClick={() => setSummaryRange(range)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  summaryRange === range
                    ? "bg-brand-card text-white shadow-sm"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {RANGE_LABELS[range]}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                <th className="px-6 py-3 text-left">Market</th>
                <th className="px-6 py-3 text-right">Predictions</th>
                <th className="px-6 py-3 text-right">Correct</th>
                <th className="px-6 py-3 text-right">Accuracy</th>
                <th className="px-6 py-3 text-right">Avg Edge</th>
                <th className="px-6 py-3 text-right">Confidence</th>
                <th className="px-4 py-3 text-right hidden lg:table-cell">Staked</th>
                <th className="px-4 py-3 text-right hidden lg:table-cell">Returned</th>
                <th className="px-6 py-3 text-right">P&amp;L</th>
                <th className="px-6 py-3 text-right">ROI</th>
              </tr>
            </thead>
            <tbody>
              {MARKETS.map((market) => {
                const ms = activeSummary[market];
                const isEmpty = !ms || ms.total_predictions === 0;
                const isSelected = selectedMarket === market;

                return (
                  <tr
                    key={market}
                    className={`border-b border-brand-border/50 transition-colors ${
                      isEmpty
                        ? "opacity-40"
                        : "cursor-pointer hover:bg-brand-surface/50"
                    } ${isSelected ? "bg-accent-green/[0.03]" : ""}`}
                    onClick={() => {
                      if (isEmpty) return;
                      setSelectedMarket(isSelected ? null : market);
                    }}
                  >
                    <td className="px-6 py-3">
                      <span
                        className={`text-xs px-2 py-1 rounded-md font-semibold uppercase border ${
                          MARKET_COLORS[market] || "bg-gray-500/15 text-gray-400 border-gray-500/25"
                        }`}
                      >
                        {market}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-300">
                      {isEmpty ? "--" : ms.total_predictions.toLocaleString()}
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-300">
                      {isEmpty ? "--" : ms.correct_predictions.toLocaleString()}
                    </td>
                    <td className="px-6 py-3 text-right">
                      {isEmpty ? (
                        <span className="font-mono text-gray-600">--</span>
                      ) : (
                        <div className="flex items-center justify-end gap-3">
                          <span
                            className={`font-mono text-sm min-w-[48px] text-right ${accuracyColor(
                              market,
                              ms.accuracy_pct
                            )}`}
                          >
                            {ms.accuracy_pct.toFixed(1)}%
                          </span>
                          <div className="w-[80px] h-1.5 bg-brand-bg rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                MARKET_BAR_COLORS[market] || "bg-gray-500"
                              }`}
                              style={{ width: `${Math.min(ms.accuracy_pct, 100)}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-300">
                      {isEmpty ? "--" : `${(ms.avg_edge * 100).toFixed(2)}%`}
                    </td>
                    <td
                      className={`px-6 py-3 text-right font-mono ${
                        isEmpty ? "text-gray-600" : confidenceColor(ms?.avg_confidence ?? 0)
                      }`}
                    >
                      {isEmpty ? "--" : ms.avg_confidence}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-400 text-sm hidden lg:table-cell">
                      {isEmpty ? "--" : `${ms.total_staked.toFixed(1)}u`}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-400 text-sm hidden lg:table-cell">
                      {isEmpty ? "--" : `${ms.total_returned.toFixed(1)}u`}
                    </td>
                    <td
                      className={`px-6 py-3 text-right font-mono ${
                        isEmpty ? "text-gray-600" : plColor(ms.profit_loss)
                      }`}
                    >
                      {isEmpty ? "--" : formatPL(ms.profit_loss)}
                    </td>
                    <td
                      className={`px-6 py-3 text-right font-mono ${
                        isEmpty ? "text-gray-600" : plColor(ms.roi_pct)
                      }`}
                    >
                      {isEmpty ? "--" : `${ms.roi_pct >= 0 ? "+" : ""}${ms.roi_pct.toFixed(1)}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Daily Breakdown */}
      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-brand-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-white">Daily Breakdown</h2>
            {selectedMarket && (
              <span
                className={`text-xs px-2 py-0.5 rounded-md uppercase border ${
                  MARKET_COLORS[selectedMarket] || "bg-gray-500/15 text-gray-400 border-gray-500/25"
                }`}
              >
                {selectedMarket}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <input
              type="date"
              value={filterDate}
              onChange={(e) => setFilterDate(e.target.value)}
              max={new Date().toISOString().slice(0, 10)}
              min={data.date_range?.earliest || ""}
              className="bg-brand-surface border border-brand-border rounded-lg px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-accent-blue/50 [color-scheme:dark]"
            />
            {(selectedMarket || filterDate) && (
              <button
                onClick={() => {
                  setSelectedMarket(null);
                  setFilterDate("");
                }}
                className="text-xs text-gray-400 hover:text-white transition-colors"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        {(showPerDate ? filteredDaily : filteredAggregated).length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No accuracy data available{filterDate ? ` for ${filterDate}` : ""}. Settlement tracking populates this after matches complete.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                  <th className="px-6 py-3 text-left">{showPerDate ? "Date" : "Period"}</th>
                  <th className="px-6 py-3 text-left">Market</th>
                  <th className="px-6 py-3 text-right">Predictions</th>
                  <th className="px-6 py-3 text-right">Correct</th>
                  <th className="px-6 py-3 text-right">Accuracy</th>
                  <th className="px-6 py-3 text-right">Avg Edge</th>
                  <th className="px-6 py-3 text-right">Confidence</th>
                  <th className="px-4 py-3 text-right hidden lg:table-cell">Staked</th>
                  <th className="px-4 py-3 text-right hidden lg:table-cell">Returned</th>
                  <th className="px-6 py-3 text-right">P&amp;L</th>
                  <th className="px-6 py-3 text-right">ROI</th>
                </tr>
              </thead>
              <tbody>
                {showPerDate
                  ? filteredDaily.map((r, i) => (
                      <DailyRow key={i} r={r} dateLabel={r.date} />
                    ))
                  : filteredAggregated.map((r) => (
                      <DailyRow key={r.market} r={r} dateLabel={r.date_range} />
                    ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Footer metadata */}
      {data.date_range?.earliest && (
        <div className="mt-4 flex gap-6 text-xs text-gray-600">
          <span>Data from {data.date_range.earliest} to {data.date_range.latest}</span>
          <span>{data.date_range.total_days} day{data.date_range.total_days !== 1 ? "s" : ""} of data</span>
        </div>
      )}
    </div>
  );
}

/* ─── DailyRow (shared between aggregated and per-date views) ─── */

function DailyRow({
  r,
  dateLabel,
}: {
  r: {
    market: string;
    total_predictions: number;
    correct_predictions: number;
    accuracy_pct: number;
    avg_edge: number;
    avg_confidence: number;
    total_staked?: number;
    total_returned?: number;
    profit_loss?: number;
    roi_pct?: number;
  };
  dateLabel: string;
}) {
  return (
    <tr className="border-b border-brand-border/50 hover:bg-brand-surface/50 transition-colors">
      <td className="px-6 py-3 text-sm text-gray-400">{dateLabel}</td>
      <td className="px-6 py-3">
        <span
          className={`text-xs px-2 py-0.5 rounded-md uppercase border ${
            MARKET_COLORS[r.market] || "bg-gray-500/15 text-gray-400 border-gray-500/25"
          }`}
        >
          {r.market}
        </span>
      </td>
      <td className="px-6 py-3 text-right font-mono text-gray-300">
        {r.total_predictions}
      </td>
      <td className="px-6 py-3 text-right font-mono text-gray-300">
        {r.correct_predictions}
      </td>
      <td className={`px-6 py-3 text-right font-mono ${accuracyColor(r.market, r.accuracy_pct)}`}>
        {r.accuracy_pct.toFixed(1)}%
      </td>
      <td className="px-6 py-3 text-right font-mono text-gray-300">
        {(r.avg_edge * 100).toFixed(2)}%
      </td>
      <td className={`px-6 py-3 text-right font-mono ${confidenceColor(r.avg_confidence)}`}>
        {r.avg_confidence}
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-400 text-sm hidden lg:table-cell">
        {(r.total_staked ?? 0).toFixed(1)}u
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-400 text-sm hidden lg:table-cell">
        {(r.total_returned ?? 0).toFixed(1)}u
      </td>
      <td className={`px-6 py-3 text-right font-mono ${plColor(r.profit_loss ?? 0)}`}>
        {formatPL(r.profit_loss ?? 0)}
      </td>
      <td className={`px-6 py-3 text-right font-mono ${plColor(r.roi_pct ?? 0)}`}>
        {(r.roi_pct ?? 0) >= 0 ? "+" : ""}
        {(r.roi_pct ?? 0).toFixed(1)}%
      </td>
    </tr>
  );
}

/* ─── SummaryCard (matches Dashboard pattern) ─── */

function SummaryCard({
  label,
  value,
  suffix,
  accent,
  icon,
}: {
  label: string;
  value: number | string;
  suffix?: string;
  accent?: "green" | "amber" | "red";
  icon: string;
}) {
  const accentColorMap = {
    green: "text-accent-green",
    amber: "text-accent-amber",
    red: "text-accent-red",
  };
  const iconColorMap = {
    green: "bg-accent-green/10 text-accent-green",
    amber: "bg-accent-amber/10 text-accent-amber",
    red: "bg-accent-red/10 text-accent-red",
  };

  return (
    <div className="bg-brand-card border border-brand-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500">{label}</span>
        <div
          className={`w-8 h-8 rounded-lg flex items-center justify-center ${
            accent ? iconColorMap[accent] : "bg-gray-500/10 text-gray-400"
          }`}
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
          </svg>
        </div>
      </div>
      <div
        className={`text-2xl font-bold ${accent ? accentColorMap[accent] : "text-white"}`}
      >
        {value}
        {suffix}
      </div>
    </div>
  );
}
