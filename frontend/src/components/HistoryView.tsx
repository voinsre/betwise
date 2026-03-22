"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { getHistory, HistoryResponse, HistoryFixture, HistoryPrediction } from "@/lib/api";
import PeriodSelector from "@/components/PeriodSelector";
import ResultBadge from "@/components/ResultBadge";

const MARKET_LABELS: Record<string, string> = {
  dc: "DC",
  ou25: "O/U 2.5",
};

function confidenceColor(confidence: number): string {
  if (confidence >= 80) return "bg-accent-green/10 text-accent-green";
  if (confidence >= 65) return "bg-accent-amber/10 text-accent-amber";
  return "bg-gray-500/10 text-gray-400";
}

function edgeColor(edge: number): string {
  if (edge >= 5) return "text-accent-green";
  if (edge >= 2) return "text-accent-amber";
  return "text-gray-400";
}

function profitColor(value: number): string {
  if (value > 0) return "text-accent-green";
  if (value < 0) return "text-accent-red";
  return "text-gray-400";
}

export default function HistoryView() {
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>("7d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selectedMarket, setSelectedMarket] = useState("all");
  const [expandedFixture, setExpandedFixture] = useState<number | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params: Record<string, string | boolean> = { value_only: true };
      if (selectedPeriod) params.period = selectedPeriod;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (selectedMarket !== "all") params.market = selectedMarket;
      const result = await getHistory(params as Parameters<typeof getHistory>[0]);
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, [selectedPeriod, dateFrom, dateTo, selectedMarket]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handlePeriodChange = useCallback((period: string) => {
    setSelectedPeriod(period);
    setDateFrom("");
    setDateTo("");
  }, []);

  const handleDateRangeChange = useCallback((from: string, to: string) => {
    setDateFrom(from);
    setDateTo(to);
    if (from || to) setSelectedPeriod(null);
  }, []);

  // Group fixtures by date for date headers
  const fixturesByDate = useMemo(() => {
    if (!data) return [];
    const groups: { date: string; fixtures: HistoryFixture[] }[] = [];
    let currentDate = "";
    for (const fix of data.fixtures) {
      if (fix.date !== currentDate) {
        currentDate = fix.date;
        groups.push({ date: currentDate, fixtures: [] });
      }
      groups[groups.length - 1].fixtures.push(fix);
    }
    return groups;
  }, [data]);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-accent-green border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-400">Loading history...</p>
        </div>
      </div>
    );
  }

  const summary = data?.summary;

  return (
    <div className="p-6 sm:p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Prediction History</h1>
        <p className="text-gray-500 text-sm mt-1">
          Track record of AI-selected value bets
        </p>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {/* Period selector */}
      <div className="mb-6">
        <PeriodSelector
          selectedPeriod={selectedPeriod}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onPeriodChange={handlePeriodChange}
          onDateRangeChange={handleDateRangeChange}
        />
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <SummaryCard
            label="Total Bets"
            value={summary.total_bets}
            icon="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
          />
          <SummaryCard
            label="Hit Rate"
            value={`${summary.hit_rate}`}
            suffix="%"
            accent={summary.hit_rate >= 55 ? "green" : summary.hit_rate >= 50 ? "amber" : "red"}
            icon="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
          />
          <SummaryCard
            label="P&L"
            value={`${summary.total_profit > 0 ? "+" : ""}${summary.total_profit}`}
            suffix="u"
            accent={summary.total_profit > 0 ? "green" : summary.total_profit < 0 ? "red" : undefined}
            icon="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
          <SummaryCard
            label="ROI"
            value={`${summary.roi > 0 ? "+" : ""}${summary.roi}`}
            suffix="%"
            accent={summary.roi > 0 ? "green" : summary.roi < 0 ? "red" : undefined}
            icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
          />
        </div>
      )}

      {/* Market filter pills */}
      <div className="flex flex-wrap items-center gap-2 mb-6">
        {["all", "dc", "ou25"].map((m) => (
          <button
            key={m}
            onClick={() => setSelectedMarket(m)}
            className={`px-3 py-1 text-xs rounded-full border transition-colors ${
              selectedMarket === m
                ? "bg-accent-green/15 border-accent-green/40 text-accent-green"
                : "border-brand-border text-gray-500 hover:text-gray-300 hover:border-gray-500"
            }`}
          >
            {m === "all" ? "All Markets" : MARKET_LABELS[m] || m.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Results table */}
      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
        {!data || data.fixtures.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No settled predictions for this period. Check back after today&apos;s matches are completed.
          </div>
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                    <th className="px-4 py-3 text-left">Date</th>
                    <th className="px-4 py-3 text-left">Home</th>
                    <th className="px-4 py-3 text-left">Away</th>
                    <th className="px-4 py-3 text-left">Selection</th>
                    <th className="px-4 py-3 text-left">Market</th>
                    <th className="px-4 py-3 text-right">Odd</th>
                    <th className="px-4 py-3 text-right">Edge%</th>
                    <th className="px-4 py-3 text-center">Result</th>
                    <th className="px-4 py-3 text-center w-8" />
                  </tr>
                </thead>
                <tbody>
                  {fixturesByDate.map((group) =>
                    group.fixtures.map((fix) => {
                      // Show the best value bet in the main row
                      const valuePreds = fix.predictions.filter((p) => p.is_value_bet);
                      const bestPred = valuePreds[0];
                      if (!bestPred) return null;

                      const isExpanded = expandedFixture === fix.fixture_id;
                      const resultStatus: "won" | "lost" | "pending" =
                        bestPred.is_correct === null ? "pending" : bestPred.is_correct ? "won" : "lost";

                      return (
                        <FixtureRow
                          key={fix.fixture_id}
                          fixture={fix}
                          bestPred={bestPred}
                          resultStatus={resultStatus}
                          isExpanded={isExpanded}
                          onToggle={() =>
                            setExpandedFixture(isExpanded ? null : fix.fixture_id)
                          }
                        />
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Mobile cards */}
            <div className="sm:hidden divide-y divide-brand-border">
              {fixturesByDate.map((group) =>
                group.fixtures.map((fix) => {
                  const valuePreds = fix.predictions.filter((p) => p.is_value_bet);
                  const bestPred = valuePreds[0];
                  if (!bestPred) return null;

                  const resultStatus: "won" | "lost" | "pending" =
                    bestPred.is_correct === null ? "pending" : bestPred.is_correct ? "won" : "lost";

                  return (
                    <MobileFixtureCard
                      key={fix.fixture_id}
                      fixture={fix}
                      bestPred={bestPred}
                      resultStatus={resultStatus}
                      isExpanded={expandedFixture === fix.fixture_id}
                      onToggle={() =>
                        setExpandedFixture(
                          expandedFixture === fix.fixture_id ? null : fix.fixture_id
                        )
                      }
                    />
                  );
                })
              )}
            </div>
          </>
        )}
      </div>

      {/* By market breakdown */}
      {data && data.by_market && Object.keys(data.by_market).length > 0 && (
        <div className="mt-6 flex gap-6 text-xs text-gray-600">
          {Object.entries(data.by_market).map(([m, stats]) => (
            <span key={m}>
              {MARKET_LABELS[m] || m.toUpperCase()}: {stats.bets} bets, {stats.hit_rate}% hit,{" "}
              <span className={profitColor(stats.profit)}>
                {stats.profit > 0 ? "+" : ""}{stats.profit}u
              </span>
            </span>
          ))}
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
        className={`text-2xl font-bold ${
          accent ? accentColorMap[accent] : "text-white"
        }`}
      >
        {value}
        {suffix}
      </div>
    </div>
  );
}

function FixtureRow({
  fixture,
  bestPred,
  resultStatus,
  isExpanded,
  onToggle,
}: {
  fixture: HistoryFixture;
  bestPred: HistoryPrediction;
  resultStatus: "won" | "lost" | "pending";
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const dateStr = new Date(fixture.date + "T00:00:00").toLocaleDateString("en-GB", {
    month: "short",
    day: "numeric",
  });

  return (
    <>
      <tr
        className="border-b border-brand-border hover:bg-brand-surface/50 cursor-pointer transition-colors"
        onClick={onToggle}
      >
        <td className="px-4 py-3 text-sm text-gray-400">
          <div>{dateStr}</div>
          <div className="text-xs text-gray-600">{fixture.kickoff}</div>
        </td>
        <td className="px-4 py-3 text-sm font-medium text-white">{fixture.home_team}</td>
        <td className="px-4 py-3 text-sm font-medium text-white">
          {fixture.away_team}
          {fixture.score && (
            <span className="ml-2 text-xs text-gray-500">({fixture.score})</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm text-accent-green font-medium">{bestPred.selection}</td>
        <td className="px-4 py-3">
          <span className="text-xs px-2 py-1 bg-brand-surface border border-brand-border rounded-md text-gray-300 uppercase">
            {bestPred.market}
          </span>
        </td>
        <td className="px-4 py-3 text-sm text-right font-mono text-white">
          {bestPred.best_odd != null ? bestPred.best_odd.toFixed(2) : "-"}
        </td>
        <td className={`px-4 py-3 text-sm text-right font-mono ${edgeColor(bestPred.edge ?? 0)}`}>
          {bestPred.edge != null ? `+${bestPred.edge.toFixed(1)}%` : "-"}
        </td>
        <td className="px-4 py-3 text-center">
          <ResultBadge result={resultStatus} />
        </td>
        <td className="px-4 py-3 text-center">
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

      {isExpanded && (
        <tr>
          <td colSpan={9} className="bg-brand-surface/30 px-4 py-4 border-b border-brand-border">
            <div className="text-xs uppercase text-gray-500 mb-3 font-semibold">
              All Markets &mdash; {fixture.home_team} vs {fixture.away_team}
              {fixture.score && <span className="normal-case ml-2">({fixture.score})</span>}
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
                    <th className="pb-2 text-center">Conf</th>
                    <th className="pb-2 text-center">Value</th>
                    <th className="pb-2 text-center">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {fixture.predictions.map((p, i) => {
                    const predResult: "won" | "lost" | "pending" =
                      p.is_correct === null ? "pending" : p.is_correct ? "won" : "lost";
                    return (
                      <tr
                        key={i}
                        className={`border-t border-brand-border/50 ${
                          p.is_value_bet ? "bg-accent-green/[0.04]" : ""
                        }`}
                      >
                        <td className="py-2 text-gray-400 uppercase text-xs">{p.market}</td>
                        <td className="py-2 text-white">{p.selection}</td>
                        <td className="py-2 text-right font-mono text-gray-300">
                          {p.blended_probability.toFixed(1)}%
                        </td>
                        <td className="py-2 text-right font-mono text-white">
                          {p.best_odd != null ? p.best_odd.toFixed(2) : "-"}
                        </td>
                        <td
                          className={`py-2 text-right font-mono ${edgeColor(p.edge ?? 0)}`}
                        >
                          {p.edge != null ? `+${p.edge.toFixed(1)}%` : "-"}
                        </td>
                        <td className="py-2 text-center">
                          <span
                            className={`text-xs ${confidenceColor(p.confidence)} px-2 py-0.5 rounded-full`}
                          >
                            {p.confidence}
                          </span>
                        </td>
                        <td className="py-2 text-center">
                          {p.is_value_bet && (
                            <span className="text-accent-green text-xs font-semibold">
                              VALUE
                            </span>
                          )}
                        </td>
                        <td className="py-2 text-center">
                          <ResultBadge result={predResult} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function MobileFixtureCard({
  fixture,
  bestPred,
  resultStatus,
  isExpanded,
  onToggle,
}: {
  fixture: HistoryFixture;
  bestPred: HistoryPrediction;
  resultStatus: "won" | "lost" | "pending";
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const dateStr = new Date(fixture.date + "T00:00:00").toLocaleDateString("en-GB", {
    month: "short",
    day: "numeric",
  });

  return (
    <div className="p-4">
      <div className="cursor-pointer" onClick={onToggle}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-gray-500">
            {dateStr} {fixture.kickoff} &middot; {fixture.league}
          </span>
          <ResultBadge result={resultStatus} />
        </div>
        <div className="flex items-center justify-between mb-2">
          <div>
            <span className="text-sm font-medium text-white">{fixture.home_team}</span>
            <span className="text-gray-500 mx-2">vs</span>
            <span className="text-sm font-medium text-white">{fixture.away_team}</span>
            {fixture.score && (
              <span className="ml-2 text-xs text-gray-500">({fixture.score})</span>
            )}
          </div>
          <svg
            className={`w-4 h-4 text-gray-500 transition-transform flex-shrink-0 ${
              isExpanded ? "rotate-180" : ""
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-accent-green font-medium">{bestPred.selection}</span>
          <span className="px-1.5 py-0.5 bg-brand-surface border border-brand-border rounded text-gray-300 uppercase">
            {bestPred.market}
          </span>
          <span className="font-mono text-white">
            {bestPred.best_odd != null ? bestPred.best_odd.toFixed(2) : "-"}
          </span>
          {bestPred.edge != null && (
            <span className={`font-mono ${edgeColor(bestPred.edge)}`}>
              +{bestPred.edge.toFixed(1)}%
            </span>
          )}
        </div>
      </div>

      {isExpanded && (
        <div className="mt-3 pt-3 border-t border-brand-border/50 space-y-2">
          {fixture.predictions.map((p, i) => {
            const predResult: "won" | "lost" | "pending" =
              p.is_correct === null ? "pending" : p.is_correct ? "won" : "lost";
            return (
              <div
                key={i}
                className={`flex items-center justify-between text-xs py-1.5 px-2 rounded ${
                  p.is_value_bet ? "bg-accent-green/[0.04]" : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-gray-400 uppercase w-8">{p.market}</span>
                  <span className="text-white">{p.selection}</span>
                  {p.is_value_bet && (
                    <span className="text-accent-green font-semibold">VALUE</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-gray-300">
                    {p.best_odd != null ? p.best_odd.toFixed(2) : "-"}
                  </span>
                  <ResultBadge result={predResult} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
