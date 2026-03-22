"""
League portfolio — SINGLE SOURCE OF TRUTH.
25 competitions. OddsPapi tournament IDs hardcoded (verified 2026-03-21).

After creating this file:
1. DELETE TARGET_LEAGUE_IDS from api_football.py
2. grep -rn "TARGET_LEAGUE_IDS" backend/ and replace ALL references
3. Convert to set for O(1) lookups where used in filters
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional


class Tier(str, Enum):
    CORE = "core"
    STRONG = "strong"
    EDGE = "edge"
    SCANDINAVIAN = "scandi"
    INTERNATIONAL = "intl"

ALL_MARKETS = ["dc", "ou15", "ou25", "ou35"]


@dataclass
class LeagueConfig:
    name: str
    country: str
    api_football_id: int
    tier: Tier
    division: int
    teams: int
    matches_per_season: int
    avg_goals_per_game: float
    season_start_month: int
    season_end_month: int
    active_markets: List[str]
    min_edge_pct: float
    min_confidence_pct: float
    oddspapi_tournament_id: int = 0       # Hardcoded — no runtime discovery
    is_international: bool = False

    def is_in_season(self) -> bool:
        month = date.today().month
        if self.season_start_month <= self.season_end_month:
            return self.season_start_month <= month <= self.season_end_month
        else:
            return month >= self.season_start_month or month <= self.season_end_month


LEAGUES: List[LeagueConfig] = [
    # ── TIER 1: CORE ──
    LeagueConfig("Bundesliga", "Germany", 78, Tier.CORE, 1, 18, 306, 3.12,
                 8, 5, ALL_MARKETS, 10.0, 68, oddspapi_tournament_id=35),
    LeagueConfig("Premier League", "England", 39, Tier.CORE, 1, 20, 380, 2.84,
                 8, 5, ALL_MARKETS, 4.0, 70, oddspapi_tournament_id=17),
    LeagueConfig("Eredivisie", "Netherlands", 88, Tier.CORE, 1, 18, 306, 3.05,
                 8, 5, ALL_MARKETS, 8.0, 68, oddspapi_tournament_id=37),
    LeagueConfig("Ligue 1", "France", 61, Tier.CORE, 1, 18, 306, 2.60,
                 8, 5, ALL_MARKETS, 3.0, 68, oddspapi_tournament_id=34),

    # ── TIER 2: STRONG ──
    LeagueConfig("Serie A", "Italy", 135, Tier.STRONG, 1, 20, 380, 2.72,
                 8, 5, ALL_MARKETS, 5.0, 72, oddspapi_tournament_id=23),
    LeagueConfig("La Liga", "Spain", 140, Tier.STRONG, 1, 20, 380, 2.68,
                 8, 5, ALL_MARKETS, 5.0, 72, oddspapi_tournament_id=8),

    # ── TIER 3: EDGE ──
    LeagueConfig("Championship", "England", 40, Tier.EDGE, 2, 24, 552, 2.70,
                 8, 5, ALL_MARKETS, 15.0, 66, oddspapi_tournament_id=188),
    LeagueConfig("2. Bundesliga", "Germany", 79, Tier.EDGE, 2, 18, 306, 2.95,
                 8, 5, ALL_MARKETS, 2.5, 66, oddspapi_tournament_id=44),
    LeagueConfig("Primeira Liga", "Portugal", 94, Tier.EDGE, 1, 18, 306, 2.55,
                 8, 5, ALL_MARKETS, 3.0, 66, oddspapi_tournament_id=238),
    LeagueConfig("Belgian Pro League", "Belgium", 144, Tier.EDGE, 1, 16, 240, 2.90,
                 8, 5, ALL_MARKETS, 12.0, 66, oddspapi_tournament_id=38),
    LeagueConfig("Austrian Bundesliga", "Austria", 218, Tier.EDGE, 1, 12, 192, 3.10,
                 7, 5, ALL_MARKETS, 2.5, 66, oddspapi_tournament_id=45),
    LeagueConfig("Swiss Super League", "Switzerland", 207, Tier.EDGE, 1, 12, 192, 3.33,
                 7, 5, ALL_MARKETS, 2.5, 66, oddspapi_tournament_id=215),
    LeagueConfig("Süper Lig", "Turkey", 203, Tier.EDGE, 1, 18, 306, 2.79,
                 8, 5, ["dc", "ou25", "ou35"], 3.0, 68, oddspapi_tournament_id=52),
    LeagueConfig("Scottish Premiership", "Scotland", 179, Tier.EDGE, 1, 12, 228, 2.60,
                 8, 5, ["ou15", "ou25", "ou35"], 3.0, 68, oddspapi_tournament_id=36),
    LeagueConfig("La Liga 2", "Spain", 141, Tier.EDGE, 2, 22, 462, 2.30,
                 8, 5, ["dc", "ou15"], 2.5, 66, oddspapi_tournament_id=54),
    LeagueConfig("Ligue 2", "France", 62, Tier.EDGE, 2, 18, 306, 2.45,
                 8, 5, ALL_MARKETS, 2.5, 66, oddspapi_tournament_id=182),
    LeagueConfig("Serie B", "Italy", 136, Tier.EDGE, 2, 20, 380, 2.55,
                 8, 5, ALL_MARKETS, 2.5, 66, oddspapi_tournament_id=53),

    # ── TIER 4: SCANDINAVIAN ──
    LeagueConfig("Allsvenskan", "Sweden", 113, Tier.SCANDINAVIAN, 1, 16, 240, 2.85,
                 3, 11, ALL_MARKETS, 2.5, 66, oddspapi_tournament_id=40),
    LeagueConfig("Eliteserien", "Norway", 103, Tier.SCANDINAVIAN, 1, 16, 240, 3.00,
                 3, 11, ALL_MARKETS, 2.5, 66, oddspapi_tournament_id=20),

    # ── TIER 5: INTERNATIONAL ──
    LeagueConfig("UEFA Champions League", "Europe", 2, Tier.INTERNATIONAL, 0, 36, 189, 2.95,
                 9, 6, ALL_MARKETS, 4.0, 70, oddspapi_tournament_id=7, is_international=True),
    LeagueConfig("UEFA Europa League", "Europe", 3, Tier.INTERNATIONAL, 0, 36, 189, 2.80,
                 9, 6, ALL_MARKETS, 3.5, 68, oddspapi_tournament_id=679, is_international=True),
    LeagueConfig("UEFA Conference League", "Europe", 848, Tier.INTERNATIONAL, 0, 36, 189, 2.70,
                 9, 6, ALL_MARKETS, 3.0, 66, oddspapi_tournament_id=34480, is_international=True),
    LeagueConfig("UEFA Nations League", "Europe", 5, Tier.INTERNATIONAL, 0, 55, 176, 2.65,
                 9, 6, ["dc", "ou25"], 4.0, 70, oddspapi_tournament_id=23755, is_international=True),
    LeagueConfig("UEFA European Championship", "Europe", 4, Tier.INTERNATIONAL, 0, 24, 51, 2.40,
                 6, 7, ALL_MARKETS, 4.0, 70, oddspapi_tournament_id=1, is_international=True),
    LeagueConfig("FIFA World Cup", "World", 1, Tier.INTERNATIONAL, 0, 48, 104, 2.55,
                 6, 7, ALL_MARKETS, 4.0, 70, oddspapi_tournament_id=16, is_international=True),
]


def get_league_by_api_id(api_id: int) -> Optional[LeagueConfig]:
    return next((l for l in LEAGUES if l.api_football_id == api_id), None)

def get_leagues_by_tier(tier: Tier) -> List[LeagueConfig]:
    return [l for l in LEAGUES if l.tier == tier]

def get_active_league_ids() -> List[int]:
    return [l.api_football_id for l in LEAGUES]

def get_in_season_league_ids() -> List[int]:
    return [l.api_football_id for l in LEAGUES if l.is_in_season()]

def is_market_active(api_id: int, market_code: str) -> bool:
    league = get_league_by_api_id(api_id)
    return league is not None and market_code in league.active_markets

def get_oddspapi_tournament_ids_in_season() -> List[int]:
    """OddsPapi tournament IDs for leagues currently in season."""
    return [l.oddspapi_tournament_id for l in LEAGUES
            if l.is_in_season() and l.oddspapi_tournament_id > 0]
