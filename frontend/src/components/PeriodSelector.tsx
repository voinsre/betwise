type PeriodSelectorProps = {
  selectedPeriod: string | null;
  dateFrom: string;
  dateTo: string;
  onPeriodChange: (period: string) => void;
  onDateRangeChange: (from: string, to: string) => void;
};

const PERIODS = [
  { value: "yesterday", label: "Yesterday" },
  { value: "3d", label: "3 Days" },
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
  { value: "all", label: "All" },
];

export default function PeriodSelector({
  selectedPeriod,
  dateFrom,
  dateTo,
  onPeriodChange,
  onDateRangeChange,
}: PeriodSelectorProps) {
  return (
    <div className="space-y-3">
      {/* Period pills */}
      <div className="flex flex-wrap items-center gap-2">
        {PERIODS.map((p) => (
          <button
            key={p.value}
            onClick={() => onPeriodChange(p.value)}
            className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-colors ${
              selectedPeriod === p.value
                ? "bg-accent-green/15 border-accent-green/40 text-accent-green"
                : "border-brand-border text-gray-500 hover:text-gray-300 hover:border-gray-500"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Date range inputs */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-500">From</label>
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => onDateRangeChange(e.target.value, dateTo)}
          className="bg-brand-surface border border-brand-border rounded-lg px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-accent-green/50 [color-scheme:dark]"
        />
        <label className="text-xs text-gray-500">To</label>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => onDateRangeChange(dateFrom, e.target.value)}
          className="bg-brand-surface border border-brand-border rounded-lg px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:border-accent-green/50 [color-scheme:dark]"
        />
      </div>
    </div>
  );
}
