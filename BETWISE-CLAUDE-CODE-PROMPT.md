# BETWISE — Claude Code Engineering Brief

> **What this is:** A complete engineering specification for Claude Code to build BetWise, an AI-powered football betting intelligence platform. Follow this document section by section. Each phase builds on the previous. Do not skip ahead.

---

## PROJECT OVERVIEW

BetWise is a PWA that:
1. Ingests football data from API-Football v3 (Ultra plan, 75K calls/day)
2. Stores everything in PostgreSQL
3. Runs a hybrid Poisson + XGBoost prediction engine across 7 betting markets
4. Detects value bets (where our model probability > bookmaker implied probability) in the 1.20–2.50 odds range
5. Serves predictions via an admin dashboard and a Gemini-powered chat interface where users request tickets

**Tech Stack:**
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Celery + Redis
- Frontend: React 18 / Next.js 14, TailwindCSS, PWA
- Database: PostgreSQL 16, Redis
- ML: NumPy, SciPy, scikit-learn, XGBoost, pandas, Optuna
- Chat AI: Google Gemini 2.0 Flash (structured function calling)
- Containerization: Docker Compose

---

## PHASE 1: PROJECT SCAFFOLD & DATABASE

### 1.1 Project Structure

```
betwise/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app entry
│   │   ├── config.py                # Settings from env vars
│   │   ├── database.py              # SQLAlchemy engine + session
│   │   ├── models/                  # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── league.py
│   │   │   ├── team.py
│   │   │   ├── fixture.py
│   │   │   ├── fixture_statistics.py
│   │   │   ├── team_last20.py
│   │   │   ├── head_to_head.py
│   │   │   ├── standing.py
│   │   │   ├── injury.py
│   │   │   ├── odds.py
│   │   │   ├── prediction.py
│   │   │   ├── ticket.py
│   │   │   └── model_accuracy.py
│   │   ├── api/                     # FastAPI routers
│   │   │   ├── __init__.py
│   │   │   ├── fixtures.py
│   │   │   ├── predictions.py
│   │   │   ├── tickets.py
│   │   │   ├── admin.py
│   │   │   └── chat.py
│   │   ├── services/                # Business logic
│   │   │   ├── __init__.py
│   │   │   ├── api_football.py      # API-Football v3 client
│   │   │   ├── data_sync.py         # Scheduled sync logic
│   │   │   ├── prediction_engine.py # Poisson + ML orchestrator
│   │   │   ├── poisson_model.py     # Poisson distribution model
│   │   │   ├── ml_model.py          # XGBoost training + inference
│   │   │   ├── value_detector.py    # Edge calculation
│   │   │   ├── ticket_builder.py    # Ticket assembly + optimizer
│   │   │   ├── bankroll.py          # Kelly criterion
│   │   │   └── gemini_chat.py       # Gemini integration
│   │   └── tasks/                   # Celery tasks
│   │       ├── __init__.py
│   │       ├── celery_app.py
│   │       ├── sync_tasks.py
│   │       ├── prediction_tasks.py
│   │       └── settlement_tasks.py
│   └── tests/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.js
│   ├── public/
│   │   └── manifest.json
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx             # Landing / chat
│   │   │   ├── admin/
│   │   │   │   ├── page.tsx         # Admin dashboard
│   │   │   │   ├── fixtures/page.tsx
│   │   │   │   ├── accuracy/page.tsx
│   │   │   │   ├── settings/page.tsx
│   │   │   │   └── data-health/page.tsx
│   │   │   └── chat/
│   │   │       └── page.tsx         # User chat interface
│   │   ├── components/
│   │   │   ├── ChatInterface.tsx
│   │   │   ├── TicketCard.tsx
│   │   │   ├── FixtureRow.tsx
│   │   │   ├── PredictionBadge.tsx
│   │   │   ├── ConfidenceMeter.tsx
│   │   │   └── AdminSidebar.tsx
│   │   ├── lib/
│   │   │   ├── api.ts               # Backend API client
│   │   │   └── types.ts             # TypeScript interfaces
│   │   └── hooks/
│   │       └── useChat.ts
│   └── tsconfig.json
└── ml/
    ├── train.py                     # Training script
    ├── backtest.py                  # Walk-forward validation
    └── models/                      # Saved model artifacts
```

### 1.2 Docker Compose

```yaml
# docker-compose.yml
version: "3.9"
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: betwise
      POSTGRES_USER: betwise
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    env_file: .env
    depends_on:
      - db
      - redis
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
      - ./ml/models:/app/ml_models

  celery_worker:
    build: ./backend
    command: celery -A app.tasks.celery_app worker -l info
    env_file: .env
    depends_on:
      - db
      - redis
    volumes:
      - ./backend:/app
      - ./ml/models:/app/ml_models

  celery_beat:
    build: ./backend
    command: celery -A app.tasks.celery_app beat -l info
    env_file: .env
    depends_on:
      - db
      - redis

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend
    environment:
      NEXT_PUBLIC_API_URL: http://backend:8000

volumes:
  pgdata:
```

### 1.3 Environment Variables (.env.example)

```env
# Database
DB_HOST=db
DB_PORT=5432
DB_NAME=betwise
DB_USER=betwise
DB_PASSWORD=changeme
DATABASE_URL=postgresql+asyncpg://betwise:changeme@db:5432/betwise

# Redis
REDIS_URL=redis://redis:6379/0

# API-Football v3
API_FOOTBALL_KEY=your_api_key_here
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io

# Google Gemini
GEMINI_API_KEY=your_gemini_key_here

# Auth
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
JWT_SECRET=changeme

# Model
KELLY_MULTIPLIER=0.25
MIN_CONFIDENCE=60
MIN_EDGE=0.02
ODDS_MIN=1.20
ODDS_MAX=2.50
```

### 1.4 Database Models

Create SQLAlchemy 2.0 ORM models for these tables. Use `mapped_column`, type hints, and relationships. Every model inherits from a `Base` with `created_at` and `updated_at` timestamps.

**leagues:**
```python
id: int (PK, from API-Football)
name: str
country: str
country_code: str
season: int
type: str  # "League" or "Cup"
logo_url: str | None
has_standings: bool
has_statistics: bool
has_odds: bool
has_injuries: bool
has_predictions: bool
is_active: bool  # Whether we're tracking this league
```

**teams:**
```python
id: int (PK, from API-Football)
name: str
code: str | None
league_id: int (FK)
country: str
logo_url: str | None
founded: int | None
venue_name: str | None
venue_capacity: int | None
```

**fixtures:**
```python
id: int (PK, from API-Football)
date: date
kickoff_time: datetime (UTC)
home_team_id: int (FK)
away_team_id: int (FK)
league_id: int (FK)
season: int
round: str | None
venue: str | None
referee: str | None
status: str  # NS, 1H, HT, 2H, FT, AET, PEN, PST, CANC, ABD, AWD, WO
score_home_ht: int | None
score_away_ht: int | None
score_home_ft: int | None
score_away_ft: int | None
score_home_et: int | None
score_away_et: int | None
```

**fixture_statistics:**
```python
id: int (PK, auto)
fixture_id: int (FK)
team_id: int (FK)
shots_on_goal: int | None
shots_off_goal: int | None
total_shots: int | None
blocked_shots: int | None
shots_insidebox: int | None
shots_outsidebox: int | None
fouls: int | None
corner_kicks: int | None
offsides: int | None
ball_possession: float | None  # as decimal 0-100
yellow_cards: int | None
red_cards: int | None
goalkeeper_saves: int | None
total_passes: int | None
passes_accurate: int | None
passes_pct: float | None
expected_goals: float | None  # xG
```

**team_last20:**
```python
id: int (PK, auto)
team_id: int (FK)
fixture_id: int (FK)
date: date
opponent_id: int (FK)
venue: str  # "H" or "A"
goals_for: int
goals_against: int
xg_for: float | None
xg_against: float | None
shots_on_target: int | None
shots_total: int | None
possession: float | None
corners: int | None
result: str  # "W", "D", "L"
form_weight: float  # 1.0 (most recent) → 0.30 (oldest)
league_id: int (FK)
season: int

# Unique constraint: (team_id, fixture_id)
# Index on: team_id + date DESC (for quick last-20 retrieval)
```

**head_to_head:**
```python
id: int (PK, auto)
team1_id: int (FK)  # always the lower ID
team2_id: int (FK)  # always the higher ID
fixture_id: int (FK)
date: date
home_team_id: int (FK)
score_home: int
score_away: int
winner: str | None  # "home", "away", "draw"
total_goals: int
xg_home: float | None
xg_away: float | None
league_id: int (FK)
```

**standings:**
```python
id: int (PK, auto)
league_id: int (FK)
season: int
team_id: int (FK)
rank: int
points: int
played: int
won: int
drawn: int
lost: int
goals_for: int
goals_against: int
goal_diff: int
form: str | None  # e.g., "WWDLW"
home_played: int
home_won: int
home_drawn: int
home_lost: int
home_gf: int
home_ga: int
away_played: int
away_won: int
away_drawn: int
away_lost: int
away_gf: int
away_ga: int
last_updated: datetime
```

**injuries:**
```python
id: int (PK, auto)
fixture_id: int (FK)
team_id: int (FK)
player_id: int
player_name: str
type: str  # "Missing Fixture", "Questionable", "Injured", "Suspended"
reason: str | None
```

**odds:**
```python
id: int (PK, auto)
fixture_id: int (FK)
bookmaker_id: int
bookmaker_name: str
market: str  # "1x2", "ou25", "btts", "dc", "htft", "combo"
label: str  # "Home", "Draw", "Away", "Over 2.5", "Under 2.5", "Yes", "No", "1/1", "Home & Over 2.5", etc.
value: float  # decimal odd (e.g., 1.85)
implied_probability: float  # 1/value
fetched_at: datetime

# Index on: (fixture_id, market) for fast lookups
# We store multiple bookmakers per fixture+market to find the best odds
```

**predictions:**
```python
id: int (PK, auto)
fixture_id: int (FK)
market: str  # "1x2", "ou25", "btts", "dc", "htft", "combo"
selection: str  # "Home", "Over 2.5", "BTTS Yes", "1X", "1/1", "Home & Over 2.5", etc.
poisson_probability: float
ml_probability: float | None  # null until ML model is trained
blended_probability: float
best_odd: float  # best available bookmaker odd for this selection
best_bookmaker: str
implied_probability: float  # 1 / best_odd
edge: float  # blended_prob - implied_prob
expected_value: float  # (blended_prob * (odd-1)) - (1-blended_prob)
confidence_score: int  # 0-100
is_value_bet: bool  # edge > 0 AND odds in range AND confidence > threshold
created_at: datetime

# Unique constraint: (fixture_id, market, selection)
```

**tickets:**
```python
id: uuid (PK)
user_id: str | None
games: list[dict]  # JSONB — array of {fixture_id, market, selection, odd, probability, edge, confidence}
num_games: int
combined_odds: float  # product of individual odds
combined_probability: float  # product of individual probabilities
kelly_stake: float  # recommended stake as % of bankroll
target_odds: float | None  # what the user requested
status: str  # "pending", "won", "lost", "partial", "void"
profit_loss: float | None  # settled P&L
created_at: datetime
settled_at: datetime | None
```

**model_accuracy:**
```python
id: int (PK, auto)
date: date
market: str
league_id: int | None  # null = all leagues
total_predictions: int
correct_predictions: int
accuracy_pct: float
avg_edge: float
avg_confidence: int
total_staked: float  # simulated flat stake
total_returned: float
profit_loss: float
roi_pct: float
```

### 1.5 Alembic Migration

After defining models, generate and run the initial migration:
```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

---

## PHASE 2: API-FOOTBALL v3 CLIENT & DATA SYNC

### 2.1 API Client (`services/api_football.py`)

Build a robust async HTTP client for API-Football v3:

```python
# Key implementation details:
# - Base URL: https://v3.football.api-sports.io
# - Auth header: "x-apisports-key": API_FOOTBALL_KEY
# - Rate limiting: max 10 requests/second (use asyncio.Semaphore)
# - Retry logic: 3 retries with exponential backoff on 429/500
# - Response parsing: all responses have { "response": [...], "results": N, "paging": {...} }
# - Error handling: check "errors" field in response
# - Pagination: some endpoints paginate, handle "paging.current" and "paging.total"
# - Logging: log every request with endpoint, params, response time, status

class APIFootballClient:
    async def get_fixtures_by_date(self, date: str) -> list[dict]
        # GET /fixtures?date={YYYY-MM-DD}
        
    async def get_fixture_statistics(self, fixture_id: int) -> list[dict]
        # GET /fixtures/statistics?fixture={id}
        
    async def get_head_to_head(self, team1_id: int, team2_id: int, last: int = 20) -> list[dict]
        # GET /fixtures/headtohead?h2h={team1}-{team2}&last={last}
        
    async def get_team_statistics(self, team_id: int, league_id: int, season: int) -> dict
        # GET /teams/statistics?team={id}&league={league_id}&season={season}
        
    async def get_team_fixtures(self, team_id: int, season: int, last: int = 20) -> list[dict]
        # GET /fixtures?team={id}&season={season}&last={last}
        # Used to get last 20 games for a team
    
    async def get_odds(self, fixture_id: int) -> list[dict]
        # GET /odds?fixture={id}
        # Returns odds from all bookmakers for all markets
        
    async def get_standings(self, league_id: int, season: int) -> list[dict]
        # GET /standings?league={id}&season={season}
        
    async def get_injuries(self, fixture_id: int) -> list[dict]
        # GET /injuries?fixture={id}
        
    async def get_leagues(self) -> list[dict]
        # GET /leagues
        
    async def get_fixtures_by_league_season(self, league_id: int, season: int, status: str = "FT") -> list[dict]
        # GET /fixtures?league={id}&season={season}&status={status}
        # For historical backfill
```

### 2.2 Data Sync Service (`services/data_sync.py`)

The sync service maps API responses to database models and upserts data:

```python
class DataSyncService:
    async def sync_leagues(self)
        # Fetch all leagues, upsert into DB
        # Check coverage field for each league to set has_* flags
        
    async def sync_fixtures_for_date(self, date: str)
        # Fetch fixtures for date, upsert
        # Only for active leagues (is_active=True)
        
    async def sync_team_last20(self, team_id: int, league_id: int, season: int)
        # Fetch last 20 fixtures for team
        # For each fixture, also fetch fixture_statistics if not already stored
        # Calculate form_weight: game[0]=1.0, game[1]=0.963, ..., game[19]=0.30
        # Formula: weight = 1.0 - (index * 0.7 / 19)
        # Upsert into team_last20 table
        
    async def sync_head_to_head(self, team1_id: int, team2_id: int)
        # Fetch H2H, upsert
        # Normalize: team1_id is always min(id1, id2)
        
    async def sync_odds(self, fixture_id: int)
        # Fetch odds for fixture
        # Parse ALL markets: Match Winner, Over/Under, BTTS, Double Chance, HT/FT
        # Map API-Football market names to our market codes:
        #   "Match Winner" → "1x2" (labels: "Home", "Draw", "Away")
        #   "Goals Over/Under" → "ou25" (only extract the 2.5 line; labels: "Over 2.5", "Under 2.5")
        #   "Both Teams Score" → "btts" (labels: "Yes", "No")
        #   "Double Chance" → "dc" (labels: "1X", "12", "X2")
        #   "HT/FT Double" → "htft" (labels: "1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")
        # For each, store best available odd across all bookmakers
        # Calculate implied_probability = 1 / value
    
    async def sync_standings(self, league_id: int, season: int)
    async def sync_injuries(self, fixture_id: int)
    
    async def sync_fixture_statistics(self, fixture_id: int)
        # Fetch match stats including xG where available
        
    async def backfill_league(self, league_id: int, season: int)
        # Get ALL completed fixtures for a league+season
        # For each fixture: sync stats, update team_last20
        # Rate limited: 10 req/sec with delays
```

### 2.3 Celery Tasks (`tasks/sync_tasks.py`)

```python
# DAILY SCHEDULE (celery beat):
# 04:00 UTC — sync_daily_fixtures: fetch fixtures for today + tomorrow
# 04:05 UTC — sync_fixture_data: for each today's fixture, sync team_last20, H2H, injuries, standings
# 04:30 UTC — sync_odds: fetch pre-match odds for all today's fixtures
# 05:00 UTC — run_predictions: trigger prediction engine for all today's fixtures
# Every 2 hours (06:00-20:00 UTC) — refresh_odds: re-fetch odds, re-run value detection
# 23:00 UTC — settle_results: fetch completed fixture scores, update team_last20, settle tickets, log accuracy
# Monday 02:00 UTC — retrain_ml: retrain XGBoost with latest week's data

@celery_app.task
def sync_daily_fixtures():
    # Sync fixtures for today and tomorrow across all active leagues
    
@celery_app.task  
def sync_fixture_data(fixture_id: int):
    # For a specific fixture: sync both teams' last20, H2H, injuries, standings
    
@celery_app.task
def sync_all_odds():
    # For all today's NS (not started) fixtures, sync odds
    
@celery_app.task
def run_all_predictions():
    # For all today's fixtures with sufficient data, run prediction engine
    
@celery_app.task
def settle_completed_fixtures():
    # Fetch results, update scores, settle predictions/tickets, log accuracy
    
@celery_app.task
def backfill_historical(league_id: int, season: int):
    # Full historical backfill for one league+season
```

### 2.4 Target Leagues Configuration

```python
TARGET_LEAGUES = [
    {"id": 39,  "name": "Premier League",   "country": "England",     "tier": 1},
    {"id": 140, "name": "La Liga",           "country": "Spain",       "tier": 1},
    {"id": 135, "name": "Serie A",           "country": "Italy",       "tier": 1},
    {"id": 78,  "name": "Bundesliga",        "country": "Germany",     "tier": 1},
    {"id": 61,  "name": "Ligue 1",           "country": "France",      "tier": 1},
    {"id": 2,   "name": "Champions League",  "country": "Europe",      "tier": 1},
    {"id": 3,   "name": "Europa League",     "country": "Europe",      "tier": 1},
    {"id": 88,  "name": "Eredivisie",        "country": "Netherlands", "tier": 2},
    {"id": 94,  "name": "Primeira Liga",     "country": "Portugal",    "tier": 2},
    {"id": 179, "name": "Premiership",       "country": "Scotland",    "tier": 2},
    {"id": 203, "name": "Super Lig",         "country": "Turkey",      "tier": 2},
    {"id": 144, "name": "Pro League",        "country": "Belgium",     "tier": 2},
    {"id": 40,  "name": "Championship",      "country": "England",     "tier": 2},
    {"id": 136, "name": "Serie B",           "country": "Italy",       "tier": 2},
    {"id": 79,  "name": "2. Bundesliga",     "country": "Germany",     "tier": 2},
]

BACKFILL_SEASONS = [2023, 2024, 2025]  # 3 seasons of history
```

---

## PHASE 3: POISSON PREDICTION ENGINE

### 3.1 Poisson Model (`services/poisson_model.py`)

```python
import numpy as np
from scipy.stats import poisson

class PoissonPredictor:
    
    def predict(self, fixture_id: int) -> dict:
        """
        Main entry point. Returns probabilities for ALL markets.
        """
        # 1. Load data
        home_last20 = get_team_last20(home_team_id, venue="H")  # filter home games
        away_last20 = get_team_last20(away_team_id, venue="A")  # filter away games
        # ALSO load all 20 games regardless of venue for overall form
        home_all20 = get_team_last20(home_team_id)
        away_all20 = get_team_last20(away_team_id)
        league_stats = get_league_averages(league_id, season)
        h2h = get_h2h(home_team_id, away_team_id)
        
        # 2. Calculate attack/defense strengths
        # Use 70% venue-specific + 30% overall stats
        home_attack = self._calc_attack_strength(home_last20, home_all20, league_stats, venue_weight=0.7)
        home_defense = self._calc_defense_weakness(home_last20, home_all20, league_stats, venue_weight=0.7)
        away_attack = self._calc_attack_strength(away_last20, away_all20, league_stats, venue_weight=0.7)
        away_defense = self._calc_defense_weakness(away_last20, away_all20, league_stats, venue_weight=0.7)
        
        # 3. Calculate lambdas
        home_advantage = self._get_home_advantage(league_id)  # typically 1.15-1.35
        lambda_home = home_attack * away_defense * league_stats["avg_goals_per_game"] * home_advantage
        lambda_away = away_attack * home_defense * league_stats["avg_goals_per_game"]
        
        # Clamp lambdas to reasonable range [0.2, 4.5]
        lambda_home = np.clip(lambda_home, 0.2, 4.5)
        lambda_away = np.clip(lambda_away, 0.2, 4.5)
        
        # 4. Generate probability matrix (7x7: goals 0-6 for each team)
        max_goals = 7
        matrix = np.zeros((max_goals, max_goals))
        for i in range(max_goals):
            for j in range(max_goals):
                matrix[i][j] = poisson.pmf(i, lambda_home) * poisson.pmf(j, lambda_away)
        
        # 5. Derive all market probabilities from matrix
        return {
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "matrix": matrix,
            "markets": {
                "1x2": self._calc_1x2(matrix),
                "ou25": self._calc_over_under(matrix, 2.5),
                "btts": self._calc_btts(matrix),
                "dc": self._calc_double_chance(matrix),
                "htft": self._calc_htft(lambda_home, lambda_away),
                "combo": self._calc_best_combos(matrix, lambda_home, lambda_away),
            }
        }
    
    def _calc_attack_strength(self, venue_games, all_games, league_stats, venue_weight=0.7):
        """
        Weighted average of goals scored, with xG blend.
        venue_games: last 20 home or away games
        all_games: last 20 all games
        Each game has form_weight for recency.
        """
        # For each game, use: 0.6 * actual_goals + 0.4 * xG (if xG available, else 100% actual)
        # Apply recency weighting (form_weight field)
        # venue_score = weighted_avg(venue_games) 
        # overall_score = weighted_avg(all_games)
        # blended = venue_weight * venue_score + (1-venue_weight) * overall_score
        # Divide by league average to get strength ratio
        # Return the ratio (>1 = better than avg, <1 = worse)
        pass
    
    def _calc_defense_weakness(self, venue_games, all_games, league_stats, venue_weight=0.7):
        # Same logic but for goals CONCEDED
        # Higher value = weaker defense (concedes more than average)
        pass
    
    def _calc_1x2(self, matrix):
        home_win = np.sum(np.tril(matrix, -1))  # below diagonal
        draw = np.trace(matrix)  # diagonal
        away_win = np.sum(np.triu(matrix, 1))  # above diagonal
        # Wait — check orientation. If matrix[i][j] = P(home=i, away=j):
        # Home win: i > j → sum where row > col
        home_win = sum(matrix[i][j] for i in range(7) for j in range(7) if i > j)
        draw = sum(matrix[i][j] for i in range(7) for j in range(7) if i == j)
        away_win = sum(matrix[i][j] for i in range(7) for j in range(7) if i < j)
        return {"Home": home_win, "Draw": draw, "Away": away_win}
    
    def _calc_over_under(self, matrix, line=2.5):
        under = sum(matrix[i][j] for i in range(7) for j in range(7) if (i+j) <= int(line))
        over = 1 - under
        return {"Over 2.5": over, "Under 2.5": under}
    
    def _calc_btts(self, matrix):
        # BTTS No = P(home=0, any away) + P(any home, away=0) - P(0,0)
        home_zero = sum(matrix[0][j] for j in range(7))
        away_zero = sum(matrix[i][0] for i in range(7))
        both_zero = matrix[0][0]
        btts_no = home_zero + away_zero - both_zero
        btts_yes = 1 - btts_no
        return {"Yes": btts_yes, "No": btts_no}
    
    def _calc_double_chance(self, matrix):
        p = self._calc_1x2(matrix)
        return {
            "1X": p["Home"] + p["Draw"],
            "12": p["Home"] + p["Away"],
            "X2": p["Draw"] + p["Away"],
        }
    
    def _calc_htft(self, lambda_home, lambda_away):
        """
        Dual Poisson for HT/FT.
        Research: ~43% of goals scored in first half.
        """
        lh_ht = lambda_home * 0.43
        la_ht = lambda_away * 0.43
        lh_2h = lambda_home * 0.57
        la_2h = lambda_away * 0.57
        
        results = {}
        for ht_label, ht_cond in [("1", "home"), ("X", "draw"), ("2", "away")]:
            for ft_label, ft_cond in [("1", "home"), ("X", "draw"), ("2", "away")]:
                # Calculate P(HT result) * P(FT result | HT result)
                # This requires calculating the joint probability properly
                # P(HT=1, FT=1) = sum over all valid scorelines where 
                #   home leads at HT AND home leads at FT
                # Simplified approach: 
                #   Generate HT matrix (using ht lambdas), 
                #   For each HT scoreline, generate conditional 2H matrix,
                #   Sum up the joint probabilities
                prob = self._calc_htft_joint(lh_ht, la_ht, lh_2h, la_2h, ht_cond, ft_cond)
                results[f"{ht_label}/{ft_label}"] = prob
        
        return results
    
    def _calc_htft_joint(self, lh_ht, la_ht, lh_2h, la_2h, ht_result, ft_result):
        """Calculate P(HT result AND FT result) using independent Poisson for each half."""
        max_g = 5  # max goals per half per team
        total = 0.0
        for h1 in range(max_g):  # home goals 1st half
            for a1 in range(max_g):  # away goals 1st half
                # Check HT condition
                if ht_result == "home" and h1 <= a1: continue
                if ht_result == "draw" and h1 != a1: continue
                if ht_result == "away" and h1 >= a1: continue
                
                p_ht = poisson.pmf(h1, lh_ht) * poisson.pmf(a1, la_ht)
                
                for h2 in range(max_g):  # home goals 2nd half
                    for a2 in range(max_g):  # away goals 2nd half
                        ft_home = h1 + h2
                        ft_away = a1 + a2
                        # Check FT condition
                        if ft_result == "home" and ft_home <= ft_away: continue
                        if ft_result == "draw" and ft_home != ft_away: continue
                        if ft_result == "away" and ft_home >= ft_away: continue
                        
                        p_2h = poisson.pmf(h2, lh_2h) * poisson.pmf(a2, la_2h)
                        total += p_ht * p_2h
        return total
    
    def _calc_best_combos(self, matrix, lambda_home, lambda_away):
        """
        Calculate probability for all standard combo bets.
        Return the top 5 combos by probability.
        """
        combos = {}
        
        # Result + Over 2.5
        for result, label in [("home", "Home"), ("draw", "Draw"), ("away", "Away")]:
            prob = sum(
                matrix[i][j] for i in range(7) for j in range(7)
                if (i + j) > 2 and (
                    (result == "home" and i > j) or
                    (result == "draw" and i == j) or
                    (result == "away" and i < j)
                )
            )
            combos[f"{label} & Over 2.5"] = prob
        
        # Result + BTTS
        for result, label in [("home", "Home"), ("draw", "Draw"), ("away", "Away")]:
            prob = sum(
                matrix[i][j] for i in range(7) for j in range(7)
                if i > 0 and j > 0 and (
                    (result == "home" and i > j) or
                    (result == "draw" and i == j) or
                    (result == "away" and i < j)
                )
            )
            combos[f"{label} & BTTS"] = prob
        
        # Result + 3+ total goals
        for result, label in [("home", "Home"), ("draw", "Draw"), ("away", "Away")]:
            prob = sum(
                matrix[i][j] for i in range(7) for j in range(7)
                if (i + j) >= 3 and (
                    (result == "home" and i > j) or
                    (result == "draw" and i == j) or
                    (result == "away" and i < j)
                )
            )
            combos[f"{label} & 3+ Goals"] = prob
        
        # BTTS + Over 2.5
        combos["BTTS & Over 2.5"] = sum(
            matrix[i][j] for i in range(7) for j in range(7)
            if i > 0 and j > 0 and (i + j) > 2
        )
        
        # DC + Over 1.5
        for dc, dc_label in [("1X", lambda i,j: i>=j), ("X2", lambda i,j: i<=j), ("12", lambda i,j: i!=j)]:
            prob = sum(
                matrix[i][j] for i in range(7) for j in range(7)
                if dc_label(i,j) and (i + j) > 1
            )
            combos[f"{dc} & Over 1.5"] = prob
        
        # Sort by probability descending, return top 5
        sorted_combos = dict(sorted(combos.items(), key=lambda x: x[1], reverse=True)[:5])
        return sorted_combos
    
    def _get_home_advantage(self, league_id: int) -> float:
        """
        Calculate league-specific home advantage from this season's results.
        Returns multiplier (e.g., 1.25 means 25% boost for home team).
        """
        # Query: for all completed fixtures in this league+season,
        # what fraction were home wins?
        # home_win_rate = home_wins / total_games
        # league_avg ≈ 0.46 historically
        # home_advantage = 1 + (home_win_rate - 0.33) * 0.5
        # Clamp to [1.05, 1.45]
        pass
```

### 3.2 League Averages Helper

```python
def get_league_averages(league_id: int, season: int) -> dict:
    """
    Compute from all completed fixtures in the league this season:
    - avg_goals_per_game: total goals / total games (typically 2.4-3.0)
    - avg_home_goals: avg goals scored by home teams
    - avg_away_goals: avg goals scored by away teams
    - home_win_rate: fraction of home wins
    """
    pass
```

---

## PHASE 4: XGBOOST ML MODEL

### 4.1 Feature Engineering (`services/ml_model.py`)

```python
class MLPredictor:
    
    def build_feature_vector(self, fixture_id: int) -> np.ndarray:
        """
        Build the 32-feature vector for a single fixture.
        All features are floats, normalized where appropriate.
        """
        home_team = get_team(fixture.home_team_id)
        away_team = get_team(fixture.away_team_id)
        
        home_last20 = get_team_last20(home_team.id)
        away_last20 = get_team_last20(away_team.id)
        h2h = get_h2h(home_team.id, away_team.id)
        standings = get_standings(fixture.league_id, fixture.season)
        injuries_home = get_injuries(fixture.id, home_team.id)
        injuries_away = get_injuries(fixture.id, away_team.id)
        
        # Get Poisson outputs to feed as features
        poisson_result = poisson_predictor.predict(fixture.id)
        
        features = [
            # 1-2: Goals scored avg (weighted by recency)
            weighted_avg(home_last20, "goals_for"),
            weighted_avg(away_last20, "goals_for"),
            
            # 3-4: Goals conceded avg
            weighted_avg(home_last20, "goals_against"),
            weighted_avg(away_last20, "goals_against"),
            
            # 5-6: xG avg (fallback to goals_for if no xG)
            weighted_avg(home_last20, "xg_for", fallback="goals_for"),
            weighted_avg(away_last20, "xg_for", fallback="goals_for"),
            
            # 7-8: xGA avg
            weighted_avg(home_last20, "xg_against", fallback="goals_against"),
            weighted_avg(away_last20, "xg_against", fallback="goals_against"),
            
            # 9-10: Shots on target avg
            weighted_avg(home_last20, "shots_on_target"),
            weighted_avg(away_last20, "shots_on_target"),
            
            # 11-12: Possession avg
            weighted_avg(home_last20, "possession"),
            weighted_avg(away_last20, "possession"),
            
            # 13-14: Form points (last 5 games only, W=3, D=1, L=0)
            calc_form_points(home_last20[:5]),
            calc_form_points(away_last20[:5]),
            
            # 15-16: Clean sheet rate
            calc_rate(home_last20, lambda g: g.goals_against == 0),
            calc_rate(away_last20, lambda g: g.goals_against == 0),
            
            # 17-18: BTTS rate
            calc_rate(home_last20, lambda g: g.goals_for > 0 and g.goals_against > 0),
            calc_rate(away_last20, lambda g: g.goals_for > 0 and g.goals_against > 0),
            
            # 19-20: Over 2.5 rate
            calc_rate(home_last20, lambda g: g.goals_for + g.goals_against > 2),
            calc_rate(away_last20, lambda g: g.goals_for + g.goals_against > 2),
            
            # 21-22: League position diff, points gap
            get_position(standings, home_team.id) - get_position(standings, away_team.id),
            abs(get_points(standings, home_team.id) - get_points(standings, away_team.id)),
            
            # 23-25: H2H record (last 10)
            h2h_wins(h2h, home_team.id),
            h2h_draws(h2h),
            h2h_wins(h2h, away_team.id),
            
            # 26: H2H avg total goals
            h2h_avg_goals(h2h),
            
            # 27-28: Injury impact
            calc_injury_impact(injuries_home),  # See weighting below
            calc_injury_impact(injuries_away),
            
            # 29: Home advantage factor
            get_home_advantage(fixture.league_id),
            
            # 30-32: Poisson model outputs (Model A → Model B)
            poisson_result["markets"]["1x2"]["Home"],
            poisson_result["markets"]["1x2"]["Draw"],
            poisson_result["markets"]["1x2"]["Away"],
        ]
        
        return np.array(features, dtype=np.float32)
    
    def calc_injury_impact(self, injuries: list) -> float:
        """
        Weight missing players by position importance.
        GK = 0.15, DEF = 0.10, MID = 0.08, FWD = 0.12 per player.
        Cap at 0.50 (team is decimated).
        """
        weights = {"Goalkeeper": 0.15, "Defender": 0.10, "Midfielder": 0.08, "Attacker": 0.12}
        total = sum(weights.get(inj.position, 0.05) for inj in injuries)
        return min(total, 0.50)
```

### 4.2 Training Pipeline (`ml/train.py`)

```python
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
import optuna

# SEPARATE MODELS FOR EACH MARKET:
# - model_1x2: 3-class classification (Home/Draw/Away)
# - model_ou25: binary classification (Over/Under)
# - model_btts: binary classification (Yes/No)
# - model_htft: 9-class classification (1/1, 1/X, ..., 2/2)

# TRAINING DATA:
# - Load all completed fixtures from backfilled seasons
# - Build feature vectors for each
# - Labels come from actual match results

# WALK-FORWARD VALIDATION:
# - Train on seasons 2023 + 2024
# - Validate on season 2025
# - Use log_loss as metric (probability calibration matters more than accuracy)

# HYPERPARAMETER TUNING (Optuna):
# - n_estimators: 100-1000
# - max_depth: 3-8
# - learning_rate: 0.01-0.3
# - subsample: 0.6-1.0
# - colsample_bytree: 0.6-1.0
# - min_child_weight: 1-10
# - Objective: minimize log_loss on validation set

# SAVE MODELS:
# - Save to ml/models/{market}_model.json
# - Also save feature importance rankings
# - Also save calibration curves (reliability diagrams)

# WEEKLY RETRAIN:
# - Add latest week's results to training set
# - Retrain with same hyperparameters (full Optuna only monthly)
# - Compare new model vs old on holdout set
# - Only deploy if new model improves or matches old
```

### 4.3 Walk-Forward Backtest (`ml/backtest.py`)

```python
# For each completed fixture in the validation season:
# 1. Build feature vector using ONLY data available BEFORE the match
# 2. Get Poisson prediction
# 3. Get ML prediction
# 4. Blend them (alpha * poisson + (1-alpha) * ml)
# 5. Compare blended probability against actual outcome
# 6. If we had odds data: simulate betting on all value bets (edge > 0, odds 1.20-2.50)
# 7. Track: accuracy, log_loss, calibration, simulated ROI

# OUTPUT:
# - Per-market accuracy and log_loss
# - Calibration curve (predicted probability vs actual frequency)
# - Simulated P&L with flat staking and Kelly staking
# - Feature importance analysis
```

---

## PHASE 5: PREDICTION ENGINE ORCHESTRATOR

### 5.1 Main Engine (`services/prediction_engine.py`)

```python
class PredictionEngine:
    def __init__(self):
        self.poisson = PoissonPredictor()
        self.ml = MLPredictor()  # loads saved models
        self.alpha = self._load_alpha()  # per-market blending weights
    
    async def predict_fixture(self, fixture_id: int) -> list[Prediction]:
        """
        Run full prediction pipeline for one fixture.
        Returns list of Prediction objects for all markets + selections.
        """
        # 1. Poisson predictions
        poisson_result = self.poisson.predict(fixture_id)
        
        # 2. ML predictions (if model is trained)
        ml_result = self.ml.predict(fixture_id) if self.ml.is_ready() else None
        
        # 3. Blend
        predictions = []
        for market, selections in poisson_result["markets"].items():
            for selection, poisson_prob in selections.items():
                ml_prob = ml_result[market][selection] if ml_result else None
                
                alpha = self.alpha.get(market, 0.50)
                if ml_prob is not None:
                    blended = alpha * poisson_prob + (1 - alpha) * ml_prob
                else:
                    blended = poisson_prob
                
                # 4. Get best odds
                best_odd, best_bookmaker = get_best_odd(fixture_id, market, selection)
                
                if best_odd is None:
                    continue  # no odds available for this selection
                
                implied_prob = 1.0 / best_odd
                edge = blended - implied_prob
                ev = (blended * (best_odd - 1)) - (1 - blended)
                
                # 5. Confidence score
                confidence = self._calc_confidence(
                    poisson_prob, ml_prob, edge, fixture_id, market
                )
                
                # 6. Value bet flag
                is_value = (
                    edge > float(settings.MIN_EDGE) and
                    best_odd >= float(settings.ODDS_MIN) and
                    best_odd <= float(settings.ODDS_MAX) and
                    confidence >= int(settings.MIN_CONFIDENCE)
                )
                
                predictions.append(Prediction(
                    fixture_id=fixture_id,
                    market=market,
                    selection=selection,
                    poisson_probability=round(poisson_prob, 4),
                    ml_probability=round(ml_prob, 4) if ml_prob else None,
                    blended_probability=round(blended, 4),
                    best_odd=best_odd,
                    best_bookmaker=best_bookmaker,
                    implied_probability=round(implied_prob, 4),
                    edge=round(edge, 4),
                    expected_value=round(ev, 4),
                    confidence_score=confidence,
                    is_value_bet=is_value,
                ))
        
        # Save all predictions to DB
        await save_predictions(predictions)
        return predictions
    
    def _calc_confidence(self, poisson_prob, ml_prob, edge, fixture_id, market) -> int:
        """
        Confidence score 0-100 based on:
        - Model agreement (25%): |poisson - ml| → lower diff = higher score
        - Edge size (25%): larger edge = higher score
        - Data quality (15%): does the league have xG? Full stats?
        - Sample size (15%): how many of the 20 games have full data?
        - H2H consistency (10%): does H2H support the prediction?
        - Market consensus (10%): low variance across bookmaker odds?
        """
        score = 0.0
        
        # Model agreement (25 points max)
        if ml_prob is not None:
            agreement = 1 - abs(poisson_prob - ml_prob)
            score += agreement * 25
        else:
            score += 12.5  # neutral when no ML
        
        # Edge size (25 points max)
        edge_score = min(edge / 0.15, 1.0) * 25  # 15%+ edge = full marks
        score += max(edge_score, 0)
        
        # Data quality (15 points max) — check league coverage flags
        league = get_league(get_fixture(fixture_id).league_id)
        if league.has_statistics: score += 5
        if league.has_odds: score += 5
        if league.has_injuries: score += 5
        
        # Sample size (15 points max)
        home_games = count_team_last20_with_stats(fixture.home_team_id)
        away_games = count_team_last20_with_stats(fixture.away_team_id)
        completeness = ((home_games + away_games) / 40)  # fraction of full data
        score += completeness * 15
        
        # H2H consistency (10 points max) — does H2H agree?
        # (simplified: if prediction direction matches H2H dominant result)
        score += 5  # placeholder, refine later
        
        # Market consensus (10 points max)
        odds_variance = get_odds_variance(fixture_id, market)
        consensus = max(0, 1 - odds_variance * 10) * 10
        score += consensus
        
        return int(min(score, 100))
```

### 5.2 Value Detector (`services/value_detector.py`)

```python
class ValueDetector:
    def get_value_bets_for_date(self, date: str) -> list[dict]:
        """
        Query all predictions for a given date where is_value_bet=True.
        Return sorted by confidence_score DESC, then edge DESC.
        Include fixture info, team names, kickoff time.
        """
        pass
    
    def get_best_bets(self, date: str, n: int = 10) -> list[dict]:
        """
        Top N value bets for the day across all markets.
        """
        pass
```

---

## PHASE 6: BANKROLL & TICKET ENGINE

### 6.1 Kelly Criterion (`services/bankroll.py`)

```python
class BankrollManager:
    def __init__(self, kelly_multiplier: float = 0.25, max_stake_pct: float = 0.05):
        self.kelly_multiplier = kelly_multiplier
        self.max_stake_pct = max_stake_pct
    
    def calc_kelly_stake(self, probability: float, odd: float, bankroll: float) -> float:
        """
        Fractional Kelly Criterion.
        kelly = (p * (o-1) - (1-p)) / (o-1)
        stake = bankroll * kelly * multiplier
        Capped at max_stake_pct of bankroll.
        """
        kelly = (probability * (odd - 1) - (1 - probability)) / (odd - 1)
        kelly = max(kelly, 0)  # never negative
        stake = bankroll * kelly * self.kelly_multiplier
        max_stake = bankroll * self.max_stake_pct
        return round(min(stake, max_stake), 2)
    
    def calc_accumulator_stake(self, legs: list[dict], bankroll: float) -> float:
        """
        For multi-leg tickets.
        Combined probability = product of individual probs * correlation_discount
        correlation_discount = 0.95 per additional leg (legs are not fully independent)
        """
        combined_prob = 1.0
        for leg in legs:
            combined_prob *= leg["blended_probability"]
        
        # Correlation discount: reduce combined prob slightly per extra leg
        num_legs = len(legs)
        if num_legs > 1:
            combined_prob *= (0.95 ** (num_legs - 1))
        
        combined_odds = 1.0
        for leg in legs:
            combined_odds *= leg["best_odd"]
        
        return self.calc_kelly_stake(combined_prob, combined_odds, bankroll)
```

### 6.2 Ticket Builder (`services/ticket_builder.py`)

```python
class TicketBuilder:
    def build_ticket(
        self,
        date: str,
        num_games: int,
        target_odds: float | None = None,
        preferred_markets: list[str] | None = None,
        min_confidence: int = 60,
        bankroll: float = 1000.0,
    ) -> dict:
        """
        Assemble the optimal ticket given user constraints.
        
        Algorithm:
        1. Get all value bets for the date
        2. Filter by preferred_markets if specified
        3. Filter by min_confidence
        4. If target_odds specified: use combinatorial optimization to find
           the N-game combination whose combined odds is closest to target
           while maximizing combined probability
        5. If no target_odds: simply pick the top N by confidence * edge product
        6. Calculate combined odds, combined probability, Kelly stake
        7. Return the ticket
        """
        # Get candidate bets
        candidates = get_value_bets_for_date(date)
        
        if preferred_markets:
            candidates = [c for c in candidates if c["market"] in preferred_markets]
        
        candidates = [c for c in candidates if c["confidence_score"] >= min_confidence]
        
        # One bet per fixture (pick best market per fixture)
        best_per_fixture = {}
        for c in candidates:
            fid = c["fixture_id"]
            if fid not in best_per_fixture or c["edge"] > best_per_fixture[fid]["edge"]:
                best_per_fixture[fid] = c
        
        candidates = list(best_per_fixture.values())
        
        if len(candidates) < num_games:
            return {"error": f"Only {len(candidates)} qualifying bets found, need {num_games}"}
        
        if target_odds:
            # Combinatorial optimization: find best N-combination
            selected = self._optimize_for_target_odds(candidates, num_games, target_odds)
        else:
            # Rank by confidence * edge, pick top N
            candidates.sort(key=lambda x: x["confidence_score"] * x["edge"], reverse=True)
            selected = candidates[:num_games]
        
        # Calculate ticket metrics
        combined_odds = 1.0
        combined_prob = 1.0
        for leg in selected:
            combined_odds *= leg["best_odd"]
            combined_prob *= leg["blended_probability"]
        
        combined_prob *= (0.95 ** (num_games - 1))  # correlation discount
        
        kelly_stake = bankroll_manager.calc_accumulator_stake(selected, bankroll)
        
        return {
            "games": selected,
            "num_games": num_games,
            "combined_odds": round(combined_odds, 2),
            "combined_probability": round(combined_prob, 4),
            "combined_probability_pct": round(combined_prob * 100, 1),
            "kelly_stake": kelly_stake,
            "kelly_stake_pct": round(kelly_stake / bankroll * 100, 1),
            "target_odds": target_odds,
        }
    
    def _optimize_for_target_odds(self, candidates, n, target):
        """
        Find the n-combination from candidates whose product of odds
        is closest to target, breaking ties by highest combined probability.
        
        For small candidate pools (<50), brute force combinations.
        For larger pools, use greedy + local search.
        """
        from itertools import combinations
        
        if len(candidates) <= 50:
            best_combo = None
            best_score = float("inf")
            for combo in combinations(candidates, n):
                odds_product = 1.0
                prob_product = 1.0
                for leg in combo:
                    odds_product *= leg["best_odd"]
                    prob_product *= leg["blended_probability"]
                
                distance = abs(odds_product - target)
                # Score: minimize distance, maximize probability
                score = distance - prob_product * 0.1
                if score < best_score:
                    best_score = score
                    best_combo = combo
            return list(best_combo)
        else:
            # Greedy approach for larger pools
            # Sort by odds ascending, pick greedily to approach target
            candidates.sort(key=lambda x: x["best_odd"])
            selected = []
            remaining_target = target
            for c in candidates:
                if len(selected) >= n:
                    break
                if c["best_odd"] <= remaining_target ** (1 / (n - len(selected))):
                    selected.append(c)
                    remaining_target /= c["best_odd"]
            return selected
```

---

## PHASE 7: GEMINI CHAT INTEGRATION

### 7.1 Gemini Service (`services/gemini_chat.py`)

```python
import google.generativeai as genai

class GeminiChatService:
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=self._get_system_prompt(),
            tools=self._get_tools(),
        )
    
    def _get_system_prompt(self) -> str:
        return """
You are BetWise AI, a football betting intelligence assistant. You help users build betting tickets based on AI-powered predictions.

IMPORTANT RULES:
- You NEVER make predictions yourself. All probabilities come from the backend prediction engine.
- You use the provided functions to query predictions, build tickets, and analyze fixtures.
- You explain the model's confidence and edge clearly.
- You always remind users that no prediction is guaranteed and to bet responsibly.
- You present data in a clear, organized format.
- You understand betting terminology: odds, edge, value bet, accumulator/parlay, Kelly criterion.
- When a user asks for a ticket, extract: number of games, target odds (if mentioned), preferred markets, and date.
- If anything is ambiguous, ask for clarification.
- Star ratings: ★★★ = confidence 80+, ★★☆ = 65-79, ★☆☆ = 50-64
"""
    
    def _get_tools(self) -> list:
        return [
            # Tool 1: Get today's predictions
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name="get_predictions",
                        description="Get all predictions for a given date, optionally filtered by market and minimum confidence",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "date": genai.protos.Schema(type=genai.protos.Type.STRING, description="Date in YYYY-MM-DD format"),
                                "market": genai.protos.Schema(type=genai.protos.Type.STRING, description="Filter by market: 1x2, ou25, btts, dc, htft, combo"),
                                "min_confidence": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Minimum confidence score (0-100)"),
                                "value_only": genai.protos.Schema(type=genai.protos.Type.BOOLEAN, description="Only return value bets"),
                            },
                            required=["date"],
                        ),
                    ),
                ]
            ),
            # Tool 2: Build a ticket
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name="build_ticket",
                        description="Build an optimized betting ticket with the specified parameters",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "date": genai.protos.Schema(type=genai.protos.Type.STRING),
                                "num_games": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                                "target_odds": genai.protos.Schema(type=genai.protos.Type.NUMBER),
                                "preferred_markets": genai.protos.Schema(
                                    type=genai.protos.Type.ARRAY,
                                    items=genai.protos.Schema(type=genai.protos.Type.STRING),
                                ),
                                "min_confidence": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                            },
                            required=["date", "num_games"],
                        ),
                    ),
                ]
            ),
            # Tool 3: Analyze a specific fixture
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name="analyze_fixture",
                        description="Get deep analysis of a specific fixture including all market predictions, team stats, H2H, injuries",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "fixture_id": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                            },
                            required=["fixture_id"],
                        ),
                    ),
                ]
            ),
            # Tool 4: Swap a game in an existing ticket
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name="swap_ticket_game",
                        description="Replace one game in a ticket with the next best alternative",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "ticket_id": genai.protos.Schema(type=genai.protos.Type.STRING),
                                "fixture_id_to_remove": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                                "preference": genai.protos.Schema(type=genai.protos.Type.STRING, description="'safer' for higher prob, 'riskier' for higher odds"),
                            },
                            required=["ticket_id", "fixture_id_to_remove"],
                        ),
                    ),
                ]
            ),
        ]
    
    async def chat(self, user_message: str, history: list[dict]) -> str:
        """
        Process a user message, call tools as needed, return response.
        """
        chat_session = self.model.start_chat(history=history)
        response = chat_session.send_message(user_message)
        
        # Handle function calls
        while response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if hasattr(part, "function_call"):
                fn_name = part.function_call.name
                fn_args = dict(part.function_call.args)
                
                # Route to backend
                result = await self._execute_function(fn_name, fn_args)
                
                # Send result back to Gemini
                response = chat_session.send_message(
                    genai.protos.Content(
                        parts=[genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=fn_name,
                                response={"result": result},
                            )
                        )]
                    )
                )
            else:
                break
        
        return response.text
    
    async def _execute_function(self, name: str, args: dict) -> dict:
        if name == "get_predictions":
            return await prediction_engine.get_predictions_for_date(**args)
        elif name == "build_ticket":
            return await ticket_builder.build_ticket(**args)
        elif name == "analyze_fixture":
            return await prediction_engine.analyze_fixture(**args)
        elif name == "swap_ticket_game":
            return await ticket_builder.swap_game(**args)
```

---

## PHASE 8: FASTAPI ROUTES

### 8.1 API Endpoints

```python
# api/predictions.py
GET /api/predictions/{date}  # All predictions for a date
GET /api/predictions/{date}/value  # Only value bets
GET /api/predictions/fixture/{fixture_id}  # All markets for one fixture

# api/fixtures.py  
GET /api/fixtures/{date}  # All fixtures for a date
GET /api/fixtures/{fixture_id}/analysis  # Deep analysis of one fixture

# api/tickets.py
POST /api/tickets/build  # Build a ticket (body: {date, num_games, target_odds, markets, min_confidence, bankroll})
POST /api/tickets/{ticket_id}/swap  # Swap a game
GET /api/tickets  # List tickets
GET /api/tickets/{ticket_id}  # Get ticket details

# api/chat.py
POST /api/chat  # Send message to Gemini (body: {message, history})

# api/admin.py (protected by admin auth)
GET /api/admin/dashboard  # Today's overview
GET /api/admin/data-health  # Sync status, missing data
GET /api/admin/accuracy  # Model accuracy over time
GET /api/admin/accuracy/{market}  # Market-specific accuracy
POST /api/admin/backfill  # Trigger historical backfill
POST /api/admin/retrain  # Trigger ML retrain
PUT /api/admin/settings  # Update weights, thresholds
GET /api/admin/leagues  # List leagues with status
PUT /api/admin/leagues/{id}  # Enable/disable league
```

### 8.2 Auth

Simple JWT-based auth. Admin credentials from env vars. Generate JWT on login, validate on protected routes. Use FastAPI `Depends()` for route protection.

---

## PHASE 9: FRONTEND (PWA)

### 9.1 Admin Dashboard (`/admin`)

Protected route. Sidebar navigation with sections:

**Dashboard (main page):**
- Today's date, number of fixtures analyzed
- Summary cards: total value bets found, avg confidence, avg edge
- Table: all today's fixtures with columns: Time, Home, Away, League, Best Value Bet, Market, Odd, Edge%, Confidence (stars), Status
- Each row expandable to show all markets for that fixture
- Color coding: green for high confidence, yellow for medium, gray for low

**Data Health (`/admin/data-health`):**
- Last sync time for each data type (fixtures, odds, stats, injuries)
- API quota: calls used today / 75,000
- Missing data alerts (fixtures without odds, teams without last20, etc.)
- Backfill progress per league

**Model Accuracy (`/admin/accuracy`):**
- Date range picker
- Per-market accuracy charts (line chart over time)
- Per-league breakdown
- Simulated P&L chart (cumulative)
- ROI percentage
- Calibration chart: predicted probability bins vs actual hit rate

**Settings (`/admin/settings`):**
- Poisson/ML blend weights (alpha) per market — slider controls
- Kelly multiplier — slider
- Min confidence threshold — slider
- Min edge threshold — slider
- Odds range — min/max sliders (default 1.20–2.50)

### 9.2 Chat Interface (`/chat`)

Full-screen chat UI with:
- Message bubbles (user right, AI left)
- Ticket cards: when Gemini returns a ticket, render it as a rich card with:
  - Each game as a row: Team A vs Team B, Market, Selection, Odd, Model %, Edge, Stars
  - Footer: Combined Odds, Combined %, Kelly Stake recommendation
  - Action buttons: "Swap Game", "Regenerate", "Save Ticket"
- Quick actions at bottom: "Best bets today", "Build safe ticket", "3-game parlay"
- Chat history persists in session

### 9.3 PWA Setup

- `manifest.json` with app name, icons, theme color
- Service worker for offline caching of static assets
- Install prompt on mobile

---

## PHASE 10: SETTLEMENT & ACCURACY TRACKING

### 10.1 Settlement Task (`tasks/settlement_tasks.py`)

```python
# Runs at 23:00 UTC daily (and can be triggered manually)
# 1. Fetch all fixtures for today with status=FT (finished)
# 2. For each, fetch final score from API-Football
# 3. Update fixture record with score
# 4. Fetch fixture statistics (shots, xG, etc.)
# 5. Update team_last20 for both teams (add new game, remove oldest if >20)
# 6. For each prediction on this fixture:
#    - Determine if it was correct based on actual result
#    - Record in model_accuracy
# 7. For each ticket containing this fixture:
#    - Check if all legs are settled
#    - If all settled: mark ticket as won/lost, calculate P&L
# 8. Aggregate daily accuracy stats per market
```

### 10.2 Accuracy Logging

```python
# After settling each fixture's predictions:
# - Group by market
# - For each market: count total predictions, count correct
# - For value bets only: track simulated staking result
#   - Flat stake: assume $10 per bet
#   - Kelly stake: use the recommended stake
#   - Track: staked, returned, P&L, ROI
# - Store in model_accuracy table

# WEEKLY: compare Poisson-only vs ML-only vs Blended accuracy per market
# - If ML outperforms Poisson on a market, decrease alpha for that market by 0.05
# - If Poisson outperforms ML, increase alpha by 0.05
# - Clamp alpha to [0.20, 0.80]
```

---

## BUILD ORDER INSTRUCTIONS FOR CLAUDE CODE

Execute in this exact order. Complete each step before moving to the next. Test each phase independently.

**Step 1:** Create project structure, Docker Compose, .env.example. Get containers running.

**Step 2:** Database models + Alembic migration. Verify schema in psql.

**Step 3:** API-Football client with rate limiting, retry logic. Test with a few manual calls.

**Step 4:** Data sync service. Run initial sync for 1 league (Premier League, id=39). Verify data in DB.

**Step 5:** Celery tasks + beat schedule. Verify automated sync runs.

**Step 6:** Poisson prediction engine. Test on a few fixtures, verify probabilities sum to ~1.0 for each market.

**Step 7:** Historical backfill for all 15 leagues, 3 seasons. This takes 3-5 days.

**Step 8:** XGBoost training pipeline. Train initial models on backfilled data. Run walk-forward backtest.

**Step 9:** Prediction engine orchestrator (blend + value detection + confidence). Run on today's fixtures.

**Step 10:** Bankroll manager + ticket builder. Test ticket assembly.

**Step 11:** FastAPI routes. Test all endpoints with curl/Postman.

**Step 12:** Gemini chat integration. Test function calling flow.

**Step 13:** Admin dashboard frontend.

**Step 14:** Chat interface frontend.

**Step 15:** PWA setup, Docker production config, deployment.

**Step 16:** Live testing period. Monitor accuracy. Tune weights.

---

## IMPORTANT NOTES

- **API-Football response format:** Every response has `{"get": "...", "parameters": {...}, "errors": [], "results": N, "paging": {...}, "response": [...]}`. The actual data is in `response`.
- **xG availability:** Not all leagues/fixtures have xG. Always handle None gracefully. Fall back to actual goals.
- **Odds market mapping:** API-Football uses bet IDs and labels that need mapping. The `/odds` endpoint returns nested structure: `bookmakers[] → bets[] → values[]`. Parse carefully.
- **Rate limits:** 10 requests/second on Ultra plan. Use asyncio.Semaphore(10) and add 100ms delay between requests.
- **Time zones:** All times in UTC. The `/fixtures` endpoint accepts `timezone` parameter but store everything in UTC internally.
- **Season format:** Some leagues use year (2024) and some use year/year (2024/2025). API-Football uses the start year (2024 for 2024/2025 season).
