export interface Fixture {
  id: number;
  date: string;
  kickoff_time: string;
  home_team_id: number;
  away_team_id: number;
  home_team_name: string;
  away_team_name: string;
  league_id: number;
  league_name: string;
  status: string;
  score_home_ft: number | null;
  score_away_ft: number | null;
}

export interface Prediction {
  id: number;
  fixture_id: number;
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
}

export interface TicketGame {
  fixture_id: number;
  market: string;
  selection: string;
  odd: number;
  probability: number;
  edge: number;
  confidence: number;
  home_team: string;
  away_team: string;
}

export interface Ticket {
  id: string;
  games: TicketGame[];
  num_games: number;
  combined_odds: number;
  combined_probability: number;
  kelly_stake: number;
  target_odds: number | null;
  status: string;
  profit_loss: number | null;
  created_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  ticket?: Ticket;
}
