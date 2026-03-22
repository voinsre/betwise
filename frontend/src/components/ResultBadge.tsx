type ResultBadgeProps = {
  result: "won" | "lost" | "pending";
};

const BADGE_STYLES = {
  won: "bg-green-500/20 text-green-400 border border-green-500/30",
  lost: "bg-red-500/20 text-red-400 border border-red-500/30",
  pending: "bg-amber-500/20 text-amber-400 border border-amber-500/30",
};

const BADGE_LABELS = {
  won: "\u2705 Won",
  lost: "\u274C Lost",
  pending: "\u23F3 Pending",
};

export default function ResultBadge({ result }: ResultBadgeProps) {
  return (
    <span
      className={`inline-flex items-center text-xs font-medium px-2.5 py-1 rounded-full ${BADGE_STYLES[result]}`}
    >
      {BADGE_LABELS[result]}
    </span>
  );
}
