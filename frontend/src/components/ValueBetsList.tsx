"use client";

import { useState, useMemo } from "react";
import ValueBetCard, { type ValueBet } from "./ValueBetCard";

const MARKET_TABS = [
  { key: "all", label: "All" },
  { key: "ou25", label: "O/U 2.5" },
  { key: "btts", label: "BTTS" },
  { key: "1x2", label: "1X2" },
  { key: "dc", label: "DC" },
  { key: "htft", label: "HT/FT" },
];

const SORT_OPTIONS = [
  { key: "edge", label: "Highest Edge" },
  { key: "confidence", label: "Highest Confidence" },
  { key: "odds", label: "Best Odds" },
];

export default function ValueBetsList({ bets }: { bets: ValueBet[] }) {
  const [activeTab, setActiveTab] = useState("all");
  const [sortBy, setSortBy] = useState("edge");

  const filtered = useMemo(() => {
    let result = [...bets];

    // Filter by market
    if (activeTab !== "all") {
      result = result.filter((b) => b.market === activeTab);
    }

    // Sort
    result.sort((a, b) => {
      if (sortBy === "edge") return b.edge - a.edge;
      if (sortBy === "confidence") return b.confidence_score - a.confidence_score;
      if (sortBy === "odds") return (b.odd ?? 0) - (a.odd ?? 0);
      return 0;
    });

    return result;
  }, [bets, activeTab, sortBy]);

  return (
    <div className="mt-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <svg className="w-4 h-4 text-accent-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
          <span className="text-sm font-semibold text-white">
            Value Bets
          </span>
          <span className="text-xs text-gray-500">({bets.length})</span>
        </div>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="text-[10px] bg-brand-surface border border-brand-border rounded px-1.5 py-0.5 text-gray-400 focus:outline-none"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.key} value={opt.key}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Market filter tabs */}
      <div className="flex gap-1 mb-2 overflow-x-auto pb-1">
        {MARKET_TABS.map((tab) => {
          const count = tab.key === "all" ? bets.length : bets.filter((b) => b.market === tab.key).length;
          if (tab.key !== "all" && count === 0) return null;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-shrink-0 text-[10px] px-2.5 py-1 rounded-full border transition-colors ${
                activeTab === tab.key
                  ? "bg-accent-green/15 border-accent-green/30 text-accent-green"
                  : "bg-brand-surface border-brand-border text-gray-500 hover:text-gray-300"
              }`}
            >
              {tab.label}
              <span className="ml-1 opacity-60">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Cards grid */}
      <div className="max-h-[400px] overflow-y-auto space-y-2 pr-1 scrollbar-thin">
        {filtered.length > 0 ? (
          filtered.map((bet, i) => <ValueBetCard key={`${bet.fixture_id}-${bet.market}-${i}`} bet={bet} />)
        ) : (
          <p className="text-xs text-gray-600 text-center py-4">
            No value bets found for this market.
          </p>
        )}
      </div>
    </div>
  );
}
