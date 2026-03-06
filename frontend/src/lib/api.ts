// All API calls use relative URLs. The Next.js Route Handler at
// app/api/[...path]/route.ts proxies them to the backend using
// BACKEND_URL (a runtime env var — no build-time dependency).
const API_URL = "";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("wizerbet_token");
}

export function setToken(token: string) {
  localStorage.setItem("wizerbet_token", token);
}

export function clearToken() {
  localStorage.removeItem("wizerbet_token");
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
  top_pick_count: number;
  top_pick_correct: number;
  top_pick_accuracy_pct: number;
  value_bet_count: number;
  value_bet_correct: number;
  value_bet_accuracy_pct: number;
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
      top_pick_count: number;
      top_pick_correct: number;
      top_pick_accuracy_pct: number;
      value_bet_count: number;
      value_bet_correct: number;
      value_bet_accuracy_pct: number;
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

// --- Retrain API ---

export interface RetrainLogEntry {
  id: number;
  started_at: string | null;
  completed_at: string | null;
  status: string;
  market: string;
  train_range: string | null;
  val_range: string | null;
  train_samples: number | null;
  val_samples: number | null;
  accuracy: number | null;
  log_loss: number | null;
  best_params: Record<string, number> | null;
  duration_seconds: number | null;
  error_message: string | null;
  triggered_by: string;
}

export interface ModelMeta {
  market: string;
  retrain_date?: string;
  train_range?: string;
  val_range?: string;
  train_samples?: number;
  val_samples?: number;
  accuracy?: number;
  log_loss?: number;
  best_params?: Record<string, number>;
  feature_names?: string[];
  model_file_exists: boolean;
  error?: string;
  // Legacy fields from initial training
  train_seasons?: number[];
  val_season?: number;
}

export async function getRetrainLogs(params?: { limit?: number; market?: string }) {
  const searchParams = new URLSearchParams();
  if (params?.limit !== undefined) searchParams.set("limit", String(params.limit));
  if (params?.market) searchParams.set("market", params.market);
  const qs = searchParams.toString();
  const path = `/api/admin/retrain-logs${qs ? `?${qs}` : ""}`;

  return fetchApi<{ logs: RetrainLogEntry[]; count: number }>(path, { auth: true });
}

export async function getModelStatus() {
  return fetchApi<{ models: Record<string, ModelMeta> }>("/api/admin/model-status", {
    auth: true,
  });
}

export async function triggerRetrain() {
  return fetchApi<{ status: string; message: string }>("/api/admin/retrain", {
    method: "POST",
    auth: true,
  });
}

export async function backfillRetrainLogs() {
  return fetchApi<{ status: string; inserted?: number; message?: string }>(
    "/api/admin/retrain-backfill",
    { method: "POST", auth: true }
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
