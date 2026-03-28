"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { getDashboard, getValueBets, getPredictions } from "@/lib/api";

const ALL_MARKETS = ["dc", "ou25"] as const;
const MARKET_LABELS: Record<string, string> = {
  dc: "DC",
  ou25: "O/U 2.5",
};

interface DashboardData {
  date: string;
  fixtures_today: number;
  predictions_today: number;
  value_bets_today: number;
  active_leagues: number;
  total_fixtures_in_db: number;
}

interface PredictionRow {
  id: number;
  fixture_id: number;
  home_team: string;
  away_team: string;
  kickoff: string;
  league_id: number;
  market: string;
  selection: string;
  poisson_probability: number;
  ml_probability: number | null;
  blended_probability: number;
  best_odd: number | null;
  best_bookmaker: string | null;
  implied_probability: number | null;
  edge: number | null;
  expected_value: number | null;
  confidence_score: number;
  is_value_bet: boolean;
}

function stars(confidence: number): string {
  if (confidence >= 80) return "\u2605\u2605\u2605";
  if (confidence >= 65) return "\u2605\u2605\u2606";
  return "\u2605\u2606\u2606";
}

function confidenceColor(confidence: number): string {
  if (confidence >= 80) return "bg-accent-green/10 text-accent-green";
  if (confidence >= 65) return "bg-accent-amber/10 text-accent-amber";
  return "bg-gray-500/10 text-gray-400";
}

function edgeColor(edge: number): string {
  if (edge >= 0.05) return "text-accent-green";
  if (edge >= 0.02) return "text-accent-amber";
  return "text-gray-400";
}

function formatTime(kickoff: string): string {
  if (!kickoff) return "-";
  try {
    const d = new Date(kickoff);
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return kickoff.slice(11, 16) || "-";
  }
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function AdminDashboard() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [valueBets, setValueBets] = useState<PredictionRow[]>([]);
  const [allPredictions, setAllPredictions] = useState<PredictionRow[]>([]);
  const [expandedFixture, setExpandedFixture] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<"value" | "all">("value");
  const [selectedMarkets, setSelectedMarkets] = useState<Set<string>>(
    () => new Set(ALL_MARKETS)
  );

  const fetchData = useCallback(async () => {
    try {
      const date = todayStr();
      const [dashRes, valueRes, predsRes] = await Promise.all([
        getDashboard(),
        getValueBets(date),
        getPredictions(date),
      ]);
      setDashboard(dashRes.dashboard);
      setValueBets(valueRes.value_bets);
      setAllPredictions(predsRes.predictions);
      setError("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const toggleMarket = useCallback((market: string) => {
    setSelectedMarkets((prev) => {
      const next = new Set(prev);
      if (next.has(market)) {
        if (next.size > 1) next.delete(market);
      } else {
        next.add(market);
      }
      return next;
    });
  }, []);

  const toggleAllMarkets = useCallback(() => {
    setSelectedMarkets((prev) =>
      prev.size === ALL_MARKETS.length ? new Set([ALL_MARKETS[0]]) : new Set(ALL_MARKETS)
    );
  }, []);

  // Source data based on view mode
  const sourceData = viewMode === "value" ? valueBets : allPredictions;

  // Filter by selected markets
  const filteredData = useMemo(
    () => sourceData.filter((p) => selectedMarkets.has(p.market)),
    [sourceData, selectedMarkets]
  );

  // Group by fixture, pick best per fixture for main table
  const fixtureRows = useMemo(() => {
    const fixtureMap = new Map<number, PredictionRow>();
    for (const p of filteredData) {
      const existing = fixtureMap.get(p.fixture_id);
      if (!existing || p.confidence_score > existing.confidence_score) {
        fixtureMap.set(p.fixture_id, p);
      }
    }
    return Array.from(fixtureMap.values()).sort(
      (a, b) => b.confidence_score - a.confidence_score
    );
  }, [filteredData]);

  const avgConfidence =
    filteredData.length > 0
      ? Math.round(filteredData.reduce((s, v) => s + v.confidence_score, 0) / filteredData.length)
      : 0;
  const avgEdge =
    filteredData.length > 0
      ? filteredData.reduce((s, v) => s + (v.edge ?? 0), 0) / filteredData.length
      : 0;

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-accent-green border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-400">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">
            {dashboard?.date || todayStr()} &middot; Auto-refreshes every 5 min
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); fetchData(); }}
          className="px-4 py-2 bg-brand-card border border-brand-border rounded-lg text-sm text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <SummaryCard
          label="Fixtures Today"
          value={dashboard?.fixtures_today ?? 0}
          icon="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
        />
        <SummaryCard
          label={viewMode === "value" ? "Value Bets" : "Predictions"}
          value={filteredData.length}
          accent="green"
          icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
        />
        <SummaryCard
          label="Avg Confidence"
          value={avgConfidence}
          suffix="%"
          accent={avgConfidence >= 70 ? "green" : "amber"}
          icon="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
        />
        <SummaryCard
          label="Avg Edge"
          value={`${(avgEdge * 100).toFixed(1)}`}
          suffix="%"
          accent={avgEdge >= 0.05 ? "green" : "amber"}
          icon="M13 10V3L4 14h7v7l9-11h-7z"
        />
      </div>

      {/* Fixtures Table */}
      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-brand-border">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-white">
                Today&apos;s {viewMode === "value" ? "Value Bets" : "Predictions"}
              </h2>
              <p className="text-sm text-gray-500 mt-0.5">
                {fixtureRows.length} fixtures &middot; {filteredData.length} selections
              </p>
            </div>

            {/* View Mode Toggle */}
            <div className="flex items-center gap-1 bg-brand-surface rounded-lg p-1">
              <button
                onClick={() => setViewMode("value")}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  viewMode === "value"
                    ? "bg-accent-green/20 text-accent-green"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                Value Bets
              </button>
              <button
                onClick={() => setViewMode("all")}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  viewMode === "all"
                    ? "bg-accent-green/20 text-accent-green"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                All
              </button>
            </div>
          </div>

          {/* Market Filters */}
          <div className="flex flex-wrap items-center gap-2 mt-3">
            <button
              onClick={toggleAllMarkets}
              className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                selectedMarkets.size === ALL_MARKETS.length
                  ? "bg-accent-green/15 border-accent-green/40 text-accent-green"
                  : "border-brand-border text-gray-500 hover:text-gray-300 hover:border-gray-500"
              }`}
            >
              All Markets
            </button>
            {ALL_MARKETS.map((m) => (
              <button
                key={m}
                onClick={() => toggleMarket(m)}
                className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                  selectedMarkets.has(m)
                    ? "bg-accent-green/15 border-accent-green/40 text-accent-green"
                    : "border-brand-border text-gray-500 hover:text-gray-300 hover:border-gray-500"
                }`}
              >
                {MARKET_LABELS[m]}
              </button>
            ))}
          </div>
        </div>

        {fixtureRows.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            {viewMode === "value"
              ? "No value bets found for today. Run predictions to generate data."
              : "No predictions found for today. Run predictions to generate data."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                  <th className="px-6 py-3 text-left">Time</th>
                  <th className="px-6 py-3 text-left">Home</th>
                  <th className="px-6 py-3 text-left">Away</th>
                  <th className="px-6 py-3 text-left">Best Value Bet</th>
                  <th className="px-6 py-3 text-left">Market</th>
                  <th className="px-6 py-3 text-right">Odd</th>
                  <th className="px-6 py-3 text-right">Edge%</th>
                  <th className="px-6 py-3 text-center">Confidence</th>
                  <th className="px-6 py-3 text-center w-8" />
                </tr>
              </thead>
              <tbody>
                {fixtureRows.map((row) => {
                  const isExpanded = expandedFixture === row.fixture_id;
                  const fixturePreds = allPredictions.filter(
                    (p) => p.fixture_id === row.fixture_id
                  );
                  return (
                    <FixtureTableRow
                      key={row.fixture_id}
                      row={row}
                      isExpanded={isExpanded}
                      fixturePreds={fixturePreds}
                      onToggle={() =>
                        setExpandedFixture(isExpanded ? null : row.fixture_id)
                      }
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* DB Stats footer */}
      {dashboard && (
        <div className="mt-6 flex gap-6 text-xs text-gray-600">
          <span>Total fixtures in DB: {dashboard.total_fixtures_in_db.toLocaleString()}</span>
          <span>Active leagues: {dashboard.active_leagues}</span>
          <span>Predictions today: {dashboard.predictions_today}</span>
        </div>
      )}
    </div>
  );
}

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
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${accent ? iconColorMap[accent] : "bg-gray-500/10 text-gray-400"}`}>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
          </svg>
        </div>
      </div>
      <div className={`text-2xl font-bold ${accent ? accentColorMap[accent] : "text-white"}`}>
        {value}{suffix}
      </div>
    </div>
  );
}

function FixtureTableRow({
  row,
  isExpanded,
  fixturePreds,
  onToggle,
}: {
  row: PredictionRow;
  isExpanded: boolean;
  fixturePreds: PredictionRow[];
  onToggle: () => void;
}) {
  const rowBg =
    row.confidence_score >= 80
      ? "bg-accent-green/[0.03]"
      : row.confidence_score >= 65
      ? "bg-accent-amber/[0.02]"
      : "";

  return (
    <>
      <tr
        className={`border-b border-brand-border hover:bg-brand-surface/50 cursor-pointer transition-colors ${rowBg}`}
        onClick={onToggle}
      >
        <td className="px-6 py-3 text-sm text-gray-400">{formatTime(row.kickoff)}</td>
        <td className="px-6 py-3 text-sm font-medium text-white">{row.home_team}</td>
        <td className="px-6 py-3 text-sm font-medium text-white">{row.away_team}</td>
        <td className="px-6 py-3 text-sm text-accent-green font-medium">{row.selection}</td>
        <td className="px-6 py-3">
          <span className="text-xs px-2 py-1 bg-brand-surface border border-brand-border rounded-md text-gray-300 uppercase">
            {row.market}
          </span>
        </td>
        <td className="px-6 py-3 text-sm text-right font-mono text-white">{row.best_odd != null ? row.best_odd.toFixed(2) : "-"}</td>
        <td className={`px-6 py-3 text-sm text-right font-mono ${edgeColor(row.edge ?? 0)}`}>
          {row.edge != null ? `+${(row.edge * 100).toFixed(1)}%` : "-"}
        </td>
        <td className="px-6 py-3 text-center">
          <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${confidenceColor(row.confidence_score)}`}>
            <span>{stars(row.confidence_score)}</span>
            <span>{row.confidence_score}</span>
          </span>
        </td>
        <td className="px-6 py-3 text-center">
          <svg
            className={`w-4 h-4 text-gray-500 transition-transform ${isExpanded ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </td>
      </tr>

      {isExpanded && fixturePreds.length > 0 && (
        <tr>
          <td colSpan={9} className="bg-brand-surface/30 px-6 py-4 border-b border-brand-border">
            <div className="text-xs uppercase text-gray-500 mb-3 font-semibold">
              All Markets &mdash; {row.home_team} vs {row.away_team}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500">
                    <th className="pb-2 text-left">Market</th>
                    <th className="pb-2 text-left">Selection</th>
                    <th className="pb-2 text-right">Prob%</th>
                    <th className="pb-2 text-right">Odd</th>
                    <th className="pb-2 text-right">Edge%</th>
                    <th className="pb-2 text-right">EV</th>
                    <th className="pb-2 text-center">Conf</th>
                    <th className="pb-2 text-center">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {fixturePreds.map((p) => (
                    <tr
                      key={p.id}
                      className={`border-t border-brand-border/50 ${p.is_value_bet ? "bg-accent-green/[0.04]" : ""}`}
                    >
                      <td className="py-2 text-gray-400 uppercase text-xs">{p.market}</td>
                      <td className="py-2 text-white">{p.selection}</td>
                      <td className="py-2 text-right font-mono text-gray-300">
                        {(p.blended_probability * 100).toFixed(1)}%
                      </td>
                      <td className="py-2 text-right font-mono text-white">
                        {p.best_odd != null ? p.best_odd.toFixed(2) : "-"}
                      </td>
                      <td className={`py-2 text-right font-mono ${edgeColor(p.edge ?? 0)}`}>
                        {p.edge != null ? `${p.edge > 0 ? "+" : ""}${(p.edge * 100).toFixed(1)}%` : "-"}
                      </td>
                      <td className={`py-2 text-right font-mono ${(p.expected_value ?? 0) > 0 ? "text-accent-green" : "text-accent-red"}`}>
                        {p.expected_value != null ? `${p.expected_value > 0 ? "+" : ""}${p.expected_value.toFixed(3)}` : "-"}
                      </td>
                      <td className="py-2 text-center">
                        <span className={`text-xs ${confidenceColor(p.confidence_score)} px-2 py-0.5 rounded-full`}>
                          {p.confidence_score}
                        </span>
                      </td>
                      <td className="py-2 text-center">
                        {p.is_value_bet && (
                          <span className="text-accent-green text-xs font-semibold">VALUE</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
