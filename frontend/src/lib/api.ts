// All API calls use relative URLs. The Next.js Route Handler at
// app/api/[...path]/route.ts proxies them to the backend using
// BACKEND_URL (a runtime env var — no build-time dependency).
const API_URL = "";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("betwise_token");
}

export function setToken(token: string) {
  localStorage.setItem("betwise_token", token);
}

export function clearToken() {
  localStorage.removeItem("betwise_token");
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export async function fetchApi<T>(
  path: string,
  options?: RequestInit & { auth?: boolean }
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (options?.auth) {
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...headers,
      ...options?.headers,
    },
  });

  if (!res.ok) {
    if (res.status === 401) {
      clearToken();
    }
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API error ${res.status}: ${text}`);
  }

  return res.json();
}

// --- Admin API ---

export async function login(username: string, password: string) {
  return fetchApi<{ token: string }>("/api/admin/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function getDashboard() {
  return fetchApi<{
    dashboard: {
      date: string;
      fixtures_today: number;
      predictions_today: number;
      value_bets_today: number;
      active_leagues: number;
      total_fixtures_in_db: number;
    };
  }>("/api/admin/dashboard", { auth: true });
}

export async function getDataHealth() {
  return fetchApi<{
    health: {
      fixture_status_counts: Record<string, number>;
      fixtures_per_season: Record<string, number>;
      teams_with_form_data: number;
      latest_fixture_date: string | null;
    };
  }>("/api/admin/data-health", { auth: true });
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
}

export async function getAccuracy(params?: { days?: number; date?: string }) {
  const searchParams = new URLSearchParams();
  if (params?.days !== undefined) searchParams.set("days", String(params.days));
  if (params?.date) searchParams.set("date", params.date);
  const qs = searchParams.toString();
  const path = `/api/admin/accuracy${qs ? `?${qs}` : ""}`;

  return fetchApi<{
    accuracy: Array<{
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
    }>;
    summary_7d: Record<string, MarketSummary>;
    summary_30d: Record<string, MarketSummary>;
    summary_90d: Record<string, MarketSummary>;
    summary_all: Record<string, MarketSummary>;
    date_range: {
      earliest: string | null;
      latest: string | null;
      total_days: number;
    };
  }>(path, { auth: true });
}

export async function getMarketAccuracy(market: string) {
  return fetchApi<{
    market: string;
    accuracy: Array<{
      date: string;
      total_predictions: number;
      correct_predictions: number;
      accuracy_pct: number;
      avg_edge: number;
      roi_pct: number;
    }>;
  }>(`/api/admin/accuracy/${market}`, { auth: true });
}

export async function updateSettings(settings: {
  kelly_multiplier?: number;
  min_confidence?: number;
  min_edge?: number;
  odds_min?: number;
  odds_max?: number;
}) {
  return fetchApi<{ status: string; changes: Record<string, number> }>(
    "/api/admin/settings",
    {
      method: "PUT",
      body: JSON.stringify(settings),
      auth: true,
    }
  );
}

export async function getValueBets(dateStr: string) {
  return fetchApi<{
    date: string;
    count: number;
    value_bets: Array<{
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
      best_odd: number;
      best_bookmaker: string;
      implied_probability: number;
      edge: number;
      expected_value: number;
      confidence_score: number;
      is_value_bet: boolean;
    }>;
  }>(`/api/predictions/${dateStr}/value`);
}

export async function getPredictions(dateStr: string) {
  return fetchApi<{
    date: string;
    count: number;
    predictions: Array<{
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
      best_odd: number;
      best_bookmaker: string;
      implied_probability: number;
      edge: number;
      expected_value: number;
      confidence_score: number;
      is_value_bet: boolean;
    }>;
  }>(`/api/predictions/${dateStr}`);
}

export async function getFixtures(dateStr: string) {
  return fetchApi<{
    date: string;
    count: number;
    fixtures: Array<{
      id: number;
      kickoff_time: string;
      home_team: string;
      away_team: string;
      league: string;
      country: string;
      status: string;
      score_home_ft: number | null;
      score_away_ft: number | null;
      venue: string | null;
    }>;
  }>(`/api/fixtures/${dateStr}`);
}
