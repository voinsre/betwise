"use client";

export interface ValueBet {
  fixture_id: number;
  home_team: string;
  away_team: string;
  league_name?: string;
  market: string;
  selection: string;
  odd: number | null;
  bookmaker?: string;
  probability: number;
  edge: number;
  confidence_score: number;
  poisson_prob?: number;
  xgb_prob?: number;
}

const MARKET_COLORS: Record<string, string> = {
  "1x2": "bg-blue-500/15 text-blue-400 border-blue-500/25",
  ou25: "bg-purple-500/15 text-purple-400 border-purple-500/25",
  btts: "bg-pink-500/15 text-pink-400 border-pink-500/25",
  dc: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25",
  htft: "bg-orange-500/15 text-orange-400 border-orange-500/25",
};

function stars(confidence: number): string {
  if (confidence >= 80) return "\u2605\u2605\u2605";
  if (confidence >= 65) return "\u2605\u2605\u2606";
  return "\u2605\u2606\u2606";
}

function confidenceColor(c: number): string {
  if (c >= 80) return "text-accent-green";
  if (c >= 65) return "text-accent-amber";
  return "text-gray-400";
}

function edgeColor(e: number): string {
  if (e >= 0.10) return "text-accent-green";
  if (e >= 0.05) return "text-accent-amber";
  return "text-gray-400";
}

export default function ValueBetCard({ bet }: { bet: ValueBet }) {
  const marketClass = MARKET_COLORS[bet.market] || "bg-gray-500/15 text-gray-400 border-gray-500/25";
  const conf = bet.confidence_score ?? 0;
  const edge = bet.edge ?? 0;
  const edgePct = edge * 100;
  const prob = bet.probability ?? 0;
  const probPct = prob * 100;

  return (
    <div className="bg-brand-card border border-brand-border rounded-lg p-3 hover:border-gray-500/50 transition-colors">
      {/* Match + Market */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-white truncate">
            {bet.home_team} vs {bet.away_team}
          </p>
          {bet.league_name && (
            <p className="text-[10px] text-gray-600 truncate">{bet.league_name}</p>
          )}
        </div>
        <span className={`flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${marketClass}`}>
          {bet.market}
        </span>
      </div>

      {/* Selection + Odds */}
      <div className="flex items-center gap-2 mb-2.5">
        <span className="text-accent-green font-semibold text-sm">{bet.selection}</span>
        {bet.odd != null && (
          <span className="text-white font-mono text-sm font-bold">@{bet.odd.toFixed(2)}</span>
        )}
        {bet.bookmaker && (
          <span className="text-[10px] text-gray-600">{bet.bookmaker}</span>
        )}
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-3 text-xs mb-2">
        <div className="flex items-center gap-1">
          <span className="text-gray-600">Prob</span>
          <span className="text-gray-300 font-mono">{probPct.toFixed(0)}%</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-gray-600">Edge</span>
          <span className={`font-mono font-semibold ${edgeColor(edge)}`}>
            +{edgePct.toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className={`${confidenceColor(conf)}`}>{stars(conf)}</span>
          <span className={`font-mono ${confidenceColor(conf)}`}>{conf}</span>
        </div>
      </div>

      {/* Confidence bar */}
      <div className="h-1 bg-brand-surface rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${
            conf >= 80 ? "bg-accent-green" : conf >= 65 ? "bg-accent-amber" : "bg-gray-500"
          }`}
          style={{ width: `${Math.min(conf, 100)}%` }}
        />
      </div>
    </div>
  );
}
