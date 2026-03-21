"""Team name mapper — resolves external names to API-Football team IDs.

Used by pinnacle_sync (OddsPapi matching), elo_service (ClubElo matching),
and bootstrap_team_mappings script.

Strategy:
1. Check MANUAL_OVERRIDES for known aliases (exact match, case-insensitive)
2. Try exact match against DB team names (case-insensitive)
3. Fall back to rapidfuzz token_sort_ratio with threshold 70
"""

import logging
from typing import Optional

from rapidfuzz import fuzz

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team

logger = logging.getLogger(__name__)

# ── Manual overrides: external alias → canonical API-Football name ──
# Keys MUST be lowercase. Values must match teams.name exactly.
MANUAL_OVERRIDES: dict[str, str] = {
    # England
    "wolves": "Wolves",
    "wolverhampton wanderers": "Wolves",
    "wolverhampton": "Wolves",
    "man utd": "Manchester United",
    "man united": "Manchester United",
    "man city": "Manchester City",
    "newcastle united": "Newcastle",
    "newcastle utd": "Newcastle",
    "spurs": "Tottenham",
    "tottenham hotspur": "Tottenham",
    "west ham united": "West Ham",
    "crystal palace fc": "Crystal Palace",
    "brighton and hove albion": "Brighton",
    "brighton & hove albion": "Brighton",
    "nottingham forest": "Nottingham Forest",
    "nott'm forest": "Nottingham Forest",
    "norwich city": "Norwich",
    "leicester city": "Leicester",
    "sheffield united": "Sheffield Utd",
    "luton town": "Luton",
    "ipswich town": "Ipswich",
    "afc bournemouth": "Bournemouth",
    # France
    "psg": "Paris Saint Germain",
    "paris saint-germain": "Paris Saint Germain",
    "paris sg": "Paris Saint Germain",
    "saint-etienne": "Saint Etienne",
    "st etienne": "Saint Etienne",
    "st. etienne": "Saint Etienne",
    "stade brestois": "Stade Brestois 29",
    "brest": "Stade Brestois 29",
    "clermont": "Clermont Foot",
    # Germany
    "bayern munich": "Bayern München",
    "bayern munchen": "Bayern München",
    "bayern muenchen": "Bayern München",
    "fc bayern": "Bayern München",
    "bayer 04 leverkusen": "Bayer Leverkusen",
    "leverkusen": "Bayer Leverkusen",
    "borussia monchengladbach": "Borussia Mönchengladbach",
    "gladbach": "Borussia Mönchengladbach",
    "m'gladbach": "Borussia Mönchengladbach",
    "hoffenheim": "1899 Hoffenheim",
    "tsg hoffenheim": "1899 Hoffenheim",
    "tsg 1899 hoffenheim": "1899 Hoffenheim",
    "heidenheim": "1. FC Heidenheim",
    "fc heidenheim": "1. FC Heidenheim",
    "koln": "1. FC Köln",
    "cologne": "1. FC Köln",
    "fc koln": "1. FC Köln",
    "1. fc koln": "1. FC Köln",
    "mainz": "FSV Mainz 05",
    "mainz 05": "FSV Mainz 05",
    "freiburg": "SC Freiburg",
    "wolfsburg": "VfL Wolfsburg",
    "vfl wolfsburg": "VfL Wolfsburg",
    "bochum": "VfL Bochum",
    "stuttgart": "VfB Stuttgart",
    "dortmund": "Borussia Dortmund",
    "bvb": "Borussia Dortmund",
    "eintracht frankfurt": "Eintracht Frankfurt",
    "frankfurt": "Eintracht Frankfurt",
    "augsburg": "FC Augsburg",
    "werder": "Werder Bremen",
    "sv werder bremen": "Werder Bremen",
    "st. pauli": "FC St. Pauli",
    "st pauli": "FC St. Pauli",
    "darmstadt": "SV Darmstadt 98",
    # Italy
    "inter milan": "Inter",
    "internazionale": "Inter",
    "inter milano": "Inter",
    "ac milan": "AC Milan",
    "milan": "AC Milan",
    "as roma": "AS Roma",
    "roma": "AS Roma",
    "juve": "Juventus",
    "napoli": "Napoli",
    "hellas verona": "Hellas Verona",
    "verona": "Hellas Verona",
    # Spain
    "atletico madrid": "Atletico Madrid",
    "atlético de madrid": "Atletico Madrid",
    "atletico de madrid": "Atletico Madrid",
    "atlético madrid": "Atletico Madrid",
    "real sociedad": "Real Sociedad",
    "athletic bilbao": "Athletic Club",
    "athletic": "Athletic Club",
    "real betis balompie": "Real Betis",
    "deportivo alaves": "Alaves",
    "deportivo alavés": "Alaves",
    "rcd espanyol": "Espanyol",
    "celta de vigo": "Celta Vigo",
    "celta": "Celta Vigo",
    "rcd mallorca": "Mallorca",
    "ca osasuna": "Osasuna",
    "real valladolid": "Valladolid",
    "ud las palmas": "Las Palmas",
    # Portugal
    "porto": "FC Porto",
    "fc porto": "FC Porto",
    "sporting lisbon": "Sporting CP",
    "sporting": "Sporting CP",
    "benfica": "Benfica",
    "sl benfica": "Benfica",
    "moreirense fc": "Moreirense",
    "gil vicente": "GIL Vicente",
    # Netherlands
    "psv eindhoven": "PSV Eindhoven",
    "psv": "PSV Eindhoven",
    "az": "AZ Alkmaar",
    "fc twente": "Twente",
    "fc utrecht": "Utrecht",
    "fc groningen": "Groningen",
    "sc heerenveen": "Heerenveen",
    "nec": "NEC Nijmegen",
    # Belgium
    "club brugge": "Club Brugge KV",
    "club bruges": "Club Brugge KV",
    "standard liège": "Standard Liege",
    "standard de liège": "Standard Liege",
    "royal antwerp": "Antwerp",
    "krc genk": "Genk",
    "racing genk": "Genk",
    "st. truiden": "St. Truiden",
    "sint-truiden": "St. Truiden",
    "kv mechelen": "KV Mechelen",
    "mechelen": "KV Mechelen",
}

FUZZY_THRESHOLD = 70


def _normalize(name: str) -> str:
    """Strip common suffixes for better fuzzy matching."""
    name = name.strip()
    for suffix in (" FC", " CF", " SC", " FK", " IF", " BK", " SK"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


class TeamNameMapper:
    """Resolves external team names to API-Football team IDs."""

    def __init__(self, teams: list[tuple[int, str]]):
        """
        Args:
            teams: list of (team_id, team_name) tuples from the DB.
        """
        # name_lower → (team_id, original_name)
        self._by_name: dict[str, tuple[int, str]] = {}
        self._teams = teams
        for tid, tname in teams:
            self._by_name[tname.lower()] = (tid, tname)

    @classmethod
    async def from_db(cls, session: AsyncSession) -> "TeamNameMapper":
        """Load all teams from DB and return a mapper instance."""
        result = await session.execute(select(Team.id, Team.name))
        teams = [(row[0], row[1]) for row in result.all()]
        return cls(teams)

    def match(self, external_name: str) -> Optional[int]:
        """
        Resolve an external team name to an API-Football team ID.

        Returns team_id or None if no match found.
        """
        if not external_name:
            return None

        key = external_name.strip().lower()

        # 1. Manual override
        override_canonical = MANUAL_OVERRIDES.get(key)
        if override_canonical:
            entry = self._by_name.get(override_canonical.lower())
            if entry:
                return entry[0]

        # 2. Exact match (case-insensitive)
        entry = self._by_name.get(key)
        if entry:
            return entry[0]

        # 3. Fuzzy match
        normalized_ext = _normalize(external_name).lower()
        best_score = 0
        best_id = None

        for tid, tname in self._teams:
            normalized_db = _normalize(tname).lower()
            score = fuzz.token_sort_ratio(normalized_ext, normalized_db)
            if score > best_score:
                best_score = score
                best_id = tid

        if best_score >= FUZZY_THRESHOLD and best_id is not None:
            return best_id

        return None

    def match_with_score(
        self, external_name: str
    ) -> tuple[Optional[int], Optional[str], float]:
        """
        Like match() but also returns the matched name and score.

        Returns (team_id, matched_name, score) or (None, None, 0).
        """
        if not external_name:
            return None, None, 0

        key = external_name.strip().lower()

        # 1. Manual override
        override_canonical = MANUAL_OVERRIDES.get(key)
        if override_canonical:
            entry = self._by_name.get(override_canonical.lower())
            if entry:
                return entry[0], entry[1], 100.0

        # 2. Exact match
        entry = self._by_name.get(key)
        if entry:
            return entry[0], entry[1], 100.0

        # 3. Fuzzy match
        normalized_ext = _normalize(external_name).lower()
        best_score = 0.0
        best_id = None
        best_name = None

        for tid, tname in self._teams:
            normalized_db = _normalize(tname).lower()
            score = fuzz.token_sort_ratio(normalized_ext, normalized_db)
            if score > best_score:
                best_score = score
                best_id = tid
                best_name = tname

        if best_score >= FUZZY_THRESHOLD and best_id is not None:
            return best_id, best_name, best_score

        return None, None, best_score
