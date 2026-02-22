"use client";

interface TicketGame {
  fixture_id: number;
  home_team: string;
  away_team: string;
  market: string;
  selection: string;
  odd: number;
  bookmaker?: string;
  probability: number;
  edge: number;
  confidence: number;
}

interface TicketData {
  ticket_id: string;
  games: TicketGame[];
  num_games: number;
  combined_odds: number;
  combined_probability: number;
  combined_probability_pct?: number;
  kelly_stake: number;
  kelly_stake_pct?: number;
  target_odds: number | null;
}

const MARKET_COLORS: Record<string, string> = {
  "1x2": "bg-blue-500/15 text-blue-400",
  ou25: "bg-purple-500/15 text-purple-400",
  btts: "bg-pink-500/15 text-pink-400",
  dc: "bg-cyan-500/15 text-cyan-400",
  htft: "bg-orange-500/15 text-orange-400",
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

export default function TicketCard({
  ticket,
  onSwap,
  onRegenerate,
}: {
  ticket: TicketData;
  onSwap?: (fixtureId: number) => void;
  onRegenerate?: () => void;
}) {
  const avgConfidence =
    ticket.games.length > 0
      ? Math.round(ticket.games.reduce((s, g) => s + g.confidence, 0) / ticket.games.length)
      : 0;

  const borderGradient =
    avgConfidence >= 75
      ? "from-accent-green/40 to-accent-green/10"
      : avgConfidence >= 60
      ? "from-accent-amber/40 to-accent-amber/10"
      : "from-gray-500/30 to-gray-500/10";

  return (
    <div className="mt-3 relative">
      {/* Gradient border effect */}
      <div className={`absolute inset-0 rounded-xl bg-gradient-to-b ${borderGradient} p-px`}>
        <div className="w-full h-full bg-brand-card rounded-xl" />
      </div>

      <div className="relative rounded-xl overflow-hidden">
        {/* Header */}
        <div className="px-4 py-3 bg-brand-surface/50 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-accent-green/15 rounded-lg flex items-center justify-center">
              <svg className="w-4 h-4 text-accent-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <span className="text-sm font-bold text-white">Betting Slip</span>
              <span className="text-xs text-gray-500 ml-2">
                {ticket.num_games} leg{ticket.num_games !== 1 ? "s" : ""}
              </span>
            </div>
          </div>
          <span className="text-[10px] text-gray-600 font-mono">
            #{ticket.ticket_id.slice(0, 8)}
          </span>
        </div>

        {/* Dotted separator */}
        <div className="border-t border-dashed border-brand-border/60" />

        {/* Games */}
        <div className="px-4 py-1">
          {ticket.games.map((game, i) => (
            <div key={i}>
              <div className="py-2.5 group">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-white font-medium">
                    {game.home_team} vs {game.away_team}
                  </span>
                  {onSwap && (
                    <button
                      onClick={() => onSwap(game.fixture_id)}
                      className="text-[10px] text-gray-600 hover:text-accent-amber opacity-0 group-hover:opacity-100 transition-all"
                    >
                      swap
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${MARKET_COLORS[game.market] || "bg-gray-500/15 text-gray-400"}`}>
                    {game.market}
                  </span>
                  <span className="text-accent-green font-medium">{game.selection}</span>
                  <span className="text-white font-mono font-bold ml-auto">@{game.odd.toFixed(2)}</span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-[10px]">
                  <span className="text-gray-500">{(game.probability * 100).toFixed(0)}% prob</span>
                  <span className={`font-mono ${game.edge >= 0.05 ? "text-accent-green" : "text-accent-amber"}`}>
                    +{(game.edge * 100).toFixed(1)}% edge
                  </span>
                  <span className={confidenceColor(game.confidence)}>
                    {stars(game.confidence)} {game.confidence}
                  </span>
                </div>
              </div>
              {/* Dotted separator between games */}
              {i < ticket.games.length - 1 && (
                <div className="border-t border-dotted border-brand-border/40" />
              )}
            </div>
          ))}
        </div>

        {/* Dotted separator */}
        <div className="border-t border-dashed border-brand-border/60" />

        {/* Footer stats */}
        <div className="px-4 py-3 bg-brand-surface/30">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-[9px] uppercase tracking-wider text-gray-600 mb-0.5">Combined Odds</div>
              <div className="text-lg font-bold font-mono text-white">
                {ticket.combined_odds.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-wider text-gray-600 mb-0.5">Win Probability</div>
              <div className="text-lg font-bold font-mono text-accent-green">
                {ticket.combined_probability_pct
                  ? `${ticket.combined_probability_pct}%`
                  : `${(ticket.combined_probability * 100).toFixed(1)}%`}
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-wider text-gray-600 mb-0.5">Kelly Stake</div>
              <div className="text-lg font-bold font-mono text-accent-amber">
                {ticket.kelly_stake_pct
                  ? `${ticket.kelly_stake_pct}%`
                  : `${(ticket.kelly_stake * 100).toFixed(1)}%`}
              </div>
            </div>
          </div>

          {/* Action buttons */}
          {(onSwap || onRegenerate) && (
            <div className="flex gap-2 mt-3 pt-3 border-t border-brand-border/40">
              {onRegenerate && (
                <button
                  onClick={onRegenerate}
                  className="flex-1 text-xs py-2 bg-brand-card border border-brand-border rounded-lg text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
                >
                  Regenerate
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export type { TicketData, TicketGame };
