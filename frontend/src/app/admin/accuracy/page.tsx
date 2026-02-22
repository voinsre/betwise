"use client";

import { useEffect, useState } from "react";
import { getAccuracy } from "@/lib/api";

interface AccuracyRow {
  date: string;
  market: string;
  league_id: number | null;
  total_predictions: number;
  correct_predictions: number;
  accuracy_pct: number;
  avg_edge: number;
  avg_confidence: number;
  profit_loss: number;
  roi_pct: number;
}

const MARKETS = ["1x2", "ou25", "btts", "dc", "htft"];

export default function AccuracyPage() {
  const [accuracy, setAccuracy] = useState<AccuracyRow[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getAccuracy()
      .then((res) => setAccuracy(res.accuracy))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-screen">
        <div className="w-8 h-8 border-2 border-accent-green border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Aggregate by market
  const marketStats = MARKETS.map((market) => {
    const rows = accuracy.filter((r) => r.market === market);
    const totalPreds = rows.reduce((s, r) => s + r.total_predictions, 0);
    const correctPreds = rows.reduce((s, r) => s + r.correct_predictions, 0);
    const avgAccuracy = totalPreds > 0 ? (correctPreds / totalPreds) * 100 : 0;
    const avgEdge =
      rows.length > 0 ? rows.reduce((s, r) => s + r.avg_edge, 0) / rows.length : 0;
    const totalPL = rows.reduce((s, r) => s + r.profit_loss, 0);
    const avgROI =
      rows.length > 0 ? rows.reduce((s, r) => s + r.roi_pct, 0) / rows.length : 0;

    return {
      market,
      totalPreds,
      correctPreds,
      avgAccuracy,
      avgEdge,
      totalPL,
      avgROI,
      rows,
    };
  });

  const filtered = selectedMarket
    ? accuracy.filter((r) => r.market === selectedMarket)
    : accuracy;

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Model Accuracy</h1>
        <p className="text-gray-500 text-sm mt-1">
          Prediction performance by market (last 30 days)
        </p>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {/* Market Summary */}
      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-brand-border">
          <h2 className="text-lg font-semibold text-white">Per-Market Summary</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                <th className="px-6 py-3 text-left">Market</th>
                <th className="px-6 py-3 text-right">Total Predictions</th>
                <th className="px-6 py-3 text-right">Correct</th>
                <th className="px-6 py-3 text-right">Accuracy%</th>
                <th className="px-6 py-3 text-right">Avg Edge</th>
                <th className="px-6 py-3 text-right">P&L</th>
                <th className="px-6 py-3 text-right">ROI%</th>
              </tr>
            </thead>
            <tbody>
              {marketStats.map((ms) => (
                <tr
                  key={ms.market}
                  className={`border-b border-brand-border/50 cursor-pointer hover:bg-brand-surface/50 transition-colors ${
                    selectedMarket === ms.market ? "bg-accent-green/[0.03]" : ""
                  }`}
                  onClick={() =>
                    setSelectedMarket(
                      selectedMarket === ms.market ? null : ms.market
                    )
                  }
                >
                  <td className="px-6 py-3">
                    <span className="text-xs px-2 py-1 bg-brand-surface border border-brand-border rounded-md text-gray-300 uppercase font-medium">
                      {ms.market}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-right font-mono text-gray-300">
                    {ms.totalPreds.toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-right font-mono text-gray-300">
                    {ms.correctPreds.toLocaleString()}
                  </td>
                  <td className={`px-6 py-3 text-right font-mono ${ms.avgAccuracy >= 60 ? "text-accent-green" : ms.avgAccuracy >= 50 ? "text-accent-amber" : "text-accent-red"}`}>
                    {ms.avgAccuracy.toFixed(1)}%
                  </td>
                  <td className="px-6 py-3 text-right font-mono text-gray-300">
                    {(ms.avgEdge * 100).toFixed(2)}%
                  </td>
                  <td className={`px-6 py-3 text-right font-mono ${ms.totalPL >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                    {ms.totalPL >= 0 ? "+" : ""}
                    {ms.totalPL.toFixed(2)}
                  </td>
                  <td className={`px-6 py-3 text-right font-mono ${ms.avgROI >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                    {ms.avgROI >= 0 ? "+" : ""}
                    {ms.avgROI.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Daily Detail Table */}
      <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-brand-border flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Daily Breakdown
              {selectedMarket && (
                <span className="text-accent-green ml-2 text-sm uppercase">
                  ({selectedMarket})
                </span>
              )}
            </h2>
          </div>
          {selectedMarket && (
            <button
              onClick={() => setSelectedMarket(null)}
              className="text-xs text-gray-400 hover:text-white transition-colors"
            >
              Show all
            </button>
          )}
        </div>

        {filtered.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No accuracy data available yet. Settlement tracking will populate this after matches complete.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                  <th className="px-6 py-3 text-left">Date</th>
                  <th className="px-6 py-3 text-left">Market</th>
                  <th className="px-6 py-3 text-right">Predictions</th>
                  <th className="px-6 py-3 text-right">Correct</th>
                  <th className="px-6 py-3 text-right">Accuracy%</th>
                  <th className="px-6 py-3 text-right">Avg Edge</th>
                  <th className="px-6 py-3 text-right">P&L</th>
                  <th className="px-6 py-3 text-right">ROI%</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr key={i} className="border-b border-brand-border/50">
                    <td className="px-6 py-3 text-sm text-gray-400">{r.date}</td>
                    <td className="px-6 py-3">
                      <span className="text-xs px-2 py-0.5 bg-brand-surface border border-brand-border rounded text-gray-400 uppercase">
                        {r.market}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-300">
                      {r.total_predictions}
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-300">
                      {r.correct_predictions}
                    </td>
                    <td className={`px-6 py-3 text-right font-mono ${r.accuracy_pct >= 60 ? "text-accent-green" : r.accuracy_pct >= 50 ? "text-accent-amber" : "text-accent-red"}`}>
                      {r.accuracy_pct.toFixed(1)}%
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-gray-300">
                      {(r.avg_edge * 100).toFixed(2)}%
                    </td>
                    <td className={`px-6 py-3 text-right font-mono ${r.profit_loss >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                      {r.profit_loss >= 0 ? "+" : ""}
                      {r.profit_loss.toFixed(2)}
                    </td>
                    <td className={`px-6 py-3 text-right font-mono ${r.roi_pct >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                      {r.roi_pct >= 0 ? "+" : ""}
                      {r.roi_pct.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
