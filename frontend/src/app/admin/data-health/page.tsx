"use client";

import { useEffect, useState } from "react";
import { getDataHealth } from "@/lib/api";

interface HealthData {
  fixture_status_counts: Record<string, number>;
  fixtures_per_season: Record<string, number>;
  teams_with_form_data: number;
  latest_fixture_date: string | null;
}

export default function DataHealthPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getDataHealth()
      .then((res) => setHealth(res.health))
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

  const totalFixtures = health
    ? Object.values(health.fixture_status_counts).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Data Health</h1>
        <p className="text-gray-500 text-sm mt-1">Database status and sync overview</p>
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/20 text-accent-red text-sm px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {health && (
        <div className="space-y-6">
          {/* Overview cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Total Fixtures" value={totalFixtures.toLocaleString()} />
            <StatCard label="Teams with Form Data" value={health.teams_with_form_data.toString()} accent="green" />
            <StatCard
              label="Latest Fixture Date"
              value={health.latest_fixture_date || "N/A"}
              accent="blue"
            />
            <StatCard
              label="Fixture Statuses"
              value={Object.keys(health.fixture_status_counts).length.toString()}
            />
          </div>

          {/* Fixture Status Counts */}
          <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-brand-border">
              <h2 className="text-lg font-semibold text-white">Fixture Status Breakdown</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                    <th className="px-6 py-3 text-left">Status</th>
                    <th className="px-6 py-3 text-right">Count</th>
                    <th className="px-6 py-3 text-right">Percentage</th>
                    <th className="px-6 py-3 text-left w-1/3">Bar</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(health.fixture_status_counts)
                    .sort(([, a], [, b]) => b - a)
                    .map(([status, count]) => (
                      <tr key={status} className="border-b border-brand-border/50">
                        <td className="px-6 py-3">
                          <StatusBadge status={status} />
                        </td>
                        <td className="px-6 py-3 text-right font-mono text-white">
                          {count.toLocaleString()}
                        </td>
                        <td className="px-6 py-3 text-right font-mono text-gray-400">
                          {((count / totalFixtures) * 100).toFixed(1)}%
                        </td>
                        <td className="px-6 py-3">
                          <div className="w-full bg-brand-bg rounded-full h-2">
                            <div
                              className="bg-accent-green/60 h-2 rounded-full"
                              style={{ width: `${(count / totalFixtures) * 100}%` }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Fixtures per Season */}
          <div className="bg-brand-card border border-brand-border rounded-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-brand-border">
              <h2 className="text-lg font-semibold text-white">Fixtures per Season</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-xs uppercase text-gray-500 border-b border-brand-border">
                    <th className="px-6 py-3 text-left">Season</th>
                    <th className="px-6 py-3 text-right">Fixtures</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(health.fixtures_per_season)
                    .sort(([a], [b]) => Number(b) - Number(a))
                    .map(([season, count]) => (
                      <tr key={season} className="border-b border-brand-border/50">
                        <td className="px-6 py-3 text-white font-medium">{season}</td>
                        <td className="px-6 py-3 text-right font-mono text-gray-300">
                          {count.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "green" | "blue" | "amber";
}) {
  const colorMap = {
    green: "text-accent-green",
    blue: "text-accent-blue",
    amber: "text-accent-amber",
  };
  return (
    <div className="bg-brand-card border border-brand-border rounded-xl p-5">
      <span className="text-sm text-gray-500">{label}</span>
      <div className={`text-2xl font-bold mt-2 ${accent ? colorMap[accent] : "text-white"}`}>
        {value}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    FT: "bg-accent-green/10 text-accent-green",
    NS: "bg-accent-blue/10 text-accent-blue",
    TBD: "bg-accent-amber/10 text-accent-amber",
    PST: "bg-accent-red/10 text-accent-red",
    CANC: "bg-accent-red/10 text-accent-red",
    SUSP: "bg-accent-amber/10 text-accent-amber",
  };
  const color = colorMap[status] || "bg-gray-500/10 text-gray-400";
  return (
    <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${color}`}>
      {status}
    </span>
  );
}
