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
  top_pick_count: number;
  top_pick_correct: number;
  top_pick_accuracy_pct: number;
  value_bet_count: number;
  value_bet_correct: number;
  value_bet_accuracy_pct: number;
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
  top_pick_count: number;
  top_pick_correct: number;
  top_pick_accuracy_pct: number;
  value_bet_count: number;
  value_bet_correct: number;
  value_bet_accuracy_pct: number;
}

interface AccuracyData {
  accuracy: AccuracyRow[];
  summary_7d: Record<string, MarketSummary>;
  summary_30d: Record<string, MarketSummary>;
  summary_90d: Record<string, MarketSummary>;
  summary_all: Record<string, MarketSummary>;
  date_range: { earliest: string | null; latest: string | null; total_days: number };
}

type RangeKey = "7d" | "30d" | "90d" | "all";

/* ─── Constants ─── */

const MARKETS = ["dc", "ou15", "ou25", "ou35"];

const MARKET_COLORS: Record<string, string> = {
  dc: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  ou15: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
  ou25: "bg-amber-500/15 text-amber-400 border-amber-500/25",
  ou35: "bg-red-500/15 text-red-400 border-red-500/25",
};

const MARKET_BAR_COLORS: Record<string, string> = {
  dc: "bg-blue-500",
  ou15: "bg-emerald-500",
  ou25: "bg-amber-500",
  ou35: "bg-red-500",
};

// Market-aware top-pick accuracy thresholds: [green_min, amber_min]
// Based on random baselines: dc=66%, ou15/ou25=50%, ou35=50%
const TOP_PICK_THRESHOLDS: Record<string, [number, number]> = {
  dc: [80, 70],
  ou15: [75, 65],
  ou25: [72, 62],
  ou35: [45, 35],
};

const RANGE_LABELS: Record<RangeKey, string> = {
  "7d": "7D",
  "30d": "30D",
  "90d": "90D",
  all: "All",
};

const RANGE_DAYS: Record<RangeKey, number> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
  all: 0,
};

/* ─── Helpers ─── */

function topPickColor(market: string, pct: number): string {
  const [green, amber] = TOP_PICK_THRESHOLDS[market] || [60, 50];
  if (pct >= green) return "text-accent-green";
  if (pct >= amber) return "text-accent-amber";
  return "text-accent-red";
}

function vbColor(pct: number): string {
  if (pct >= 50) return "text-accent-green";
  if (pct >= 35) return "text-accent-amber";
  return "text-accent-red";
}

function plColor(v: number): string {
  return v >= 0 ? "text-accent-green" : "text-accent-red";
}

function formatPL(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
}

function computeKPIs(summary: Record<string, MarketSummary>) {
  let totalTopPick = 0, totalTopPickCorrect = 0;
  let totalValueBet = 0, totalValueBetCorrect = 0;
  let totalStaked = 0, totalPL = 0;
  for (const ms of Object.values(summary)) {
    totalTopPick += ms.top_pick_count ?? 0;
    totalTopPickCorrect += ms.top_pick_correct ?? 0;
    totalValueBet += ms.value_bet_count ?? 0;
    totalValueBetCorrect += ms.value_bet_correct ?? 0;
    totalStaked += ms.total_staked ?? 0;
    totalPL += ms.profit_loss ?? 0;
  }
  return {
    topPickAccuracy: totalTopPick > 0 ? (totalTopPickCorrect / totalTopPick) * 100 : 0,
    topPickCount: totalTopPick,
    valueBetAccuracy: totalValueBet > 0 ? (totalValueBetCorrect / totalValueBet) * 100 : 0,
    valueBetCount: totalValueBet,
    totalPL,
    overallROI: totalStaked > 0 ? (totalPL / totalStaked) * 100 : 0,
  };
}

/* ─── Component ─── */

export default function AccuracyPage() {
  const [data, setData] = useState<AccuracyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [summaryRange, setSummaryRange] = useState<RangeKey>("30d");

  const [selectedMarket, setSelectedMarket] = useState<string | null>(null);
  const [filterDate, setFilterDate] = useState("");

  const fetchData = useCallback(async (dateFilter?: string) => {
    try {
      const params: { days?: number; date?: string } = {};
      if (dateFilter) {
        params.date = dateFilter;
      } else {
        params.days = RANGE_DAYS[summaryRange];
      }
      const res = await getAccuracy(params);
      setData(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, [summaryRange]);

  useEffect(() => {
    setLoading(true);
    fetchData().finally(() => setLoading(false));
  }, [fetchData]);

  // Refetch when date filter changes
  useEffect(() => {
    if (!data) return;
    fetchData(filterDate || undefined);
  }, [filterDate]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const empty: Record<string, MarketSummary> = {};
  const summaryMap: Record<RangeKey, Record<string, MarketSummary>> = {
    "7d": data.summary_7d || empty,
    "30d": data.summary_30d || empty,
    "90d": data.summary_90d || empty,
    all: data.summary_all || empty,
  };
  const activeSummary = summaryMap[summaryRange];
  const kpis = computeKPIs(activeSummary);
  const rangeLabel = RANGE_LABELS[summaryRange];

  const dailyRows = data.accuracy || [];
  const filteredDaily = dailyRows
    .filter((r) => {
      if (filterDate && r.date !== filterDate) return false;
      if (selectedMarket && r.market !== selectedMarket) return false;
      return true;
    })
    .sort((a, b) => b.date.localeCompare(a.date));

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Model Accuracy</h1>
        <p className="text-gray-500 text-sm mt-1">
          Top-pick prediction skill &amp; value bet profitability
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
          label={`${rangeLabel} Top-Pick Accuracy`}
          value={kpis.topPickCount > 0 ? kpis.topPickAccuracy.toFixed(1) : "--"}
          suffix={kpis.topPickCount > 0 ? "%" : ""}
          subtext={kpis.topPickCount > 0 ? `${kpis.topPickCount} fixtures` : undefined}
          accent={kpis.topPickCount > 0 ? (kpis.topPickAccuracy >= 50 ? "green" : kpis.topPickAccuracy >= 35 ? "amber" : "red") : undefined}
          icon="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
        <SummaryCard
          label={`${rangeLabel} Value Bet Hit Rate`}
          value={kpis.valueBetCount > 0 ? kpis.valueBetAccuracy.toFixed(1) : "--"}
          suffix={kpis.valueBetCount > 0 ? "%" : ""}
          subtext={kpis.valueBetCount > 0 ? `${kpis.valueBetCount} bets` : undefined}
          accent={kpis.valueBetCount > 0 ? (kpis.valueBetAccuracy >= 50 ? "green" : kpis.valueBetAccuracy >= 35 ? "amber" : "red") : undefined}
          icon="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"
        />
        <SummaryCard
          label={`${rangeLabel} P&L (Value Bets)`}
          value={formatPL(kpis.totalPL)}
          suffix="u"
          accent={kpis.totalPL >= 0 ? "green" : "red"}
          icon="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
        <SummaryCard
          label={`${rangeLabel} ROI (Value Bets)`}
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
            {(["7d", "30d", "90d", "all"] as RangeKey[]).map((range) => (
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
                <th className="px-4 py-3 text-right">Fixtures</th>
                <th className="px-4 py-3 text-right">Top Pick</th>
                <th className="px-4 py-3 text-right hidden sm:table-cell">VB</th>
                <th className="px-4 py-3 text-right hidden sm:table-cell">VB Hit</th>
                <th className="px-4 py-3 text-right">Avg Edge</th>
                <th className="px-6 py-3 text-right">P&amp;L</th>
                <th className="px-6 py-3 text-right">ROI</th>
              </tr>
            </thead>
            <tbody>
              {MARKETS.map((market) => {
                const ms = activeSummary[market];
                const isEmpty = !ms || (ms.top_pick_count ?? 0) === 0;
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
                    <td className="px-4 py-3 text-right font-mono text-gray-300">
                      {isEmpty ? "--" : (ms.top_pick_count ?? 0)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {isEmpty ? (
                        <span className="font-mono text-gray-600">--</span>
                      ) : (
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-xs text-gray-500">
                            {ms.top_pick_correct ?? 0}/{ms.top_pick_count ?? 0}
                          </span>
                          <span
                            className={`font-mono text-sm min-w-[44px] text-right ${topPickColor(
                              market,
                              ms.top_pick_accuracy_pct ?? 0
                            )}`}
                          >
                            {(ms.top_pick_accuracy_pct ?? 0).toFixed(1)}%
                          </span>
                          <div className="w-[60px] h-1.5 bg-brand-bg rounded-full overflow-hidden hidden lg:block">
                            <div
                              className={`h-full rounded-full transition-all ${
                                MARKET_BAR_COLORS[market] || "bg-gray-500"
                              }`}
                              style={{ width: `${Math.min(ms.top_pick_accuracy_pct ?? 0, 100)}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-300 hidden sm:table-cell">
                      {isEmpty ? "--" : (ms.value_bet_count ?? 0)}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono hidden sm:table-cell ${
                      isEmpty ? "text-gray-600" : vbColor(ms.value_bet_accuracy_pct ?? 0)
                    }`}>
                      {isEmpty ? "--" : `${(ms.value_bet_accuracy_pct ?? 0).toFixed(1)}%`}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-300">
                      {isEmpty ? "--" : `${((ms.avg_edge ?? 0) * 100).toFixed(2)}%`}
                    </td>
                    <td
                      className={`px-6 py-3 text-right font-mono ${
                        isEmpty ? "text-gray-600" : plColor(ms.profit_loss ?? 0)
                      }`}
                    >
                      {isEmpty ? "--" : formatPL(ms.profit_loss ?? 0)}
                    </td>
                    <td
                      className={`px-6 py-3 text-right font-mono ${
                        isEmpty ? "text-gray-600" : plColor(ms.roi_pct ?? 0)
                      }`}
                    >
                      {isEmpty ? "--" : `${(ms.roi_pct ?? 0) >= 0 ? "+" : ""}${(ms.roi_pct ?? 0).toFixed(1)}%`}
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

        {filteredDaily.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No accuracy data available{filterDate ? ` for ${filterDate}` : ""}. Settlement tracking populates this after matches complete.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                  <th className="px-6 py-3 text-left">Date</th>
                  <th className="px-4 py-3 text-left">Market</th>
                  <th className="px-4 py-3 text-right">Fixtures</th>
                  <th className="px-4 py-3 text-right">Top Pick</th>
                  <th className="px-4 py-3 text-right hidden sm:table-cell">VB</th>
                  <th className="px-4 py-3 text-right hidden sm:table-cell">VB Hit</th>
                  <th className="px-4 py-3 text-right">Avg Edge</th>
                  <th className="px-6 py-3 text-right">P&amp;L</th>
                  <th className="px-6 py-3 text-right">ROI</th>
                </tr>
              </thead>
              <tbody>
                {filteredDaily.map((r) => (
                  <DailyRow key={`${r.date}-${r.market}`} r={r} />
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

/* ─── DailyRow ─── */

function DailyRow({ r }: { r: AccuracyRow }) {
  const tpCount = r.top_pick_count ?? 0;
  const tpCorrect = r.top_pick_correct ?? 0;
  const tpPct = r.top_pick_accuracy_pct ?? 0;
  const vbCount = r.value_bet_count ?? 0;
  const vbPct = r.value_bet_accuracy_pct ?? 0;

  return (
    <tr className="border-b border-brand-border/50 hover:bg-brand-surface/50 transition-colors">
      <td className="px-6 py-3 text-sm text-gray-400">{r.date}</td>
      <td className="px-4 py-3">
        <span
          className={`text-xs px-2 py-0.5 rounded-md uppercase border ${
            MARKET_COLORS[r.market] || "bg-gray-500/15 text-gray-400 border-gray-500/25"
          }`}
        >
          {r.market}
        </span>
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">
        {tpCount}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-2">
          <span className="text-xs text-gray-500">{tpCorrect}/{tpCount}</span>
          <span className={`font-mono text-sm ${topPickColor(r.market, tpPct)}`}>
            {tpPct.toFixed(1)}%
          </span>
        </div>
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300 hidden sm:table-cell">
        {vbCount}
      </td>
      <td className={`px-4 py-3 text-right font-mono hidden sm:table-cell ${vbCount > 0 ? vbColor(vbPct) : "text-gray-600"}`}>
        {vbCount > 0 ? `${vbPct.toFixed(1)}%` : "--"}
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">
        {((r.avg_edge ?? 0) * 100).toFixed(2)}%
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

/* ─── SummaryCard ─── */

function SummaryCard({
  label,
  value,
  suffix,
  subtext,
  accent,
  icon,
}: {
  label: string;
  value: number | string;
  suffix?: string;
  subtext?: string;
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
      {subtext && (
        <div className="text-xs text-gray-500 mt-1">{subtext}</div>
      )}
    </div>
  );
}
