"""
Football-data.co.uk weekly Pinnacle odds sync.

Downloads latest CSVs from football-data.co.uk and imports Pinnacle closing
odds for any completed fixtures that don't already have Pinnacle odds in DB.

Markets imported:
  - 1x2: PSH/PSD/PSA (Home/Draw/Away)
  - dc:  derived from 1X2 (1X, 12, X2)
  - ou25: P>2.5 / P<2.5 (Over 2.5 / Under 2.5)
"""

import csv
import logging
from datetime import datetime, timedelta, timezone
from io import StringIO

import httpx
from rapidfuzz import fuzz, process
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.fixture import Fixture
from app.models.odds import Odds

logger = logging.getLogger(__name__)

# ─── League mapping ──────────────────────────────────────────────
LEAGUE_MAP = {
    39:  {"code": "E0",  "name": "Premier League"},
    40:  {"code": "E1",  "name": "Championship"},
    78:  {"code": "D1",  "name": "Bundesliga"},
    79:  {"code": "D2",  "name": "2. Bundesliga"},
    140: {"code": "SP1", "name": "La Liga"},
    141: {"code": "SP2", "name": "La Liga 2"},
    135: {"code": "I1",  "name": "Serie A"},
    136: {"code": "I2",  "name": "Serie B"},
    61:  {"code": "F1",  "name": "Ligue 1"},
    62:  {"code": "F2",  "name": "Ligue 2"},
    88:  {"code": "N1",  "name": "Eredivisie"},
    94:  {"code": "P1",  "name": "Primeira Liga"},
    144: {"code": "B1",  "name": "Belgian Pro League"},
    203: {"code": "T1",  "name": "Super Lig"},
    179: {"code": "SC0", "name": "Scottish Premiership"},
}

BASE_URL = "https://www.football-data.co.uk/mmz4281"

SKIP_TEAMS = {"Villarreal B"}

MANUAL_OVERRIDES = {
    # EPL
    "Man United": "Manchester United",
    "Man City": "Manchester City",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "Newcastle": "Newcastle United",
    "Wolves": "Wolverhampton Wanderers",
    "West Ham": "West Ham United",
    "Tottenham": "Tottenham Hotspur",
    "Sheffield United": "Sheffield United",
    "Luton": "Luton Town",
    "Ipswich": "Ipswich Town",
    "Leicester": "Leicester City",
    "Brighton": "Brighton & Hove Albion",
    # Championship
    "Birmingham": "Birmingham City",
    "Blackburn": "Blackburn Rovers",
    "Bristol City": "Bristol City",
    "Cardiff": "Cardiff City",
    "Coventry": "Coventry City",
    "Hull": "Hull City",
    "Leeds": "Leeds United",
    "Norwich": "Norwich City",
    "Oxford": "Oxford United",
    "Plymouth": "Plymouth Argyle",
    "Preston": "Preston North End",
    "QPR": "Queens Park Rangers",
    "Sheffield Weds": "Sheffield Wednesday",
    "Stoke": "Stoke City",
    "Sunderland": "Sunderland",
    "Swansea": "Swansea",
    "West Brom": "West Bromwich Albion",
    "Middlesbrough": "Middlesbrough",
    # Bundesliga
    "Bayern Munich": "Bayern München",
    "Leverkusen": "Bayer Leverkusen",
    "Dortmund": "Borussia Dortmund",
    "M'gladbach": "Borussia Mönchengladbach",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "FC Koln": "1. FC Köln",
    "Mainz": "FSV Mainz 05",
    "Hertha": "Hertha BSC",
    "Hoffenheim": "1899 Hoffenheim",
    "Wolfsburg": "VfL Wolfsburg",
    "Stuttgart": "VfB Stuttgart",
    "Bochum": "VfL Bochum",
    "Union Berlin": "1. FC Union Berlin",
    "Augsburg": "FC Augsburg",
    "Heidenheim": "1. FC Heidenheim 1846",
    "Freiburg": "SC Freiburg",
    "Darmstadt": "SV Darmstadt 98",
    "Werder Bremen": "SV Werder Bremen",
    "RB Leipzig": "RB Leipzig",
    "FC St. Pauli": "FC St. Pauli",
    "St Pauli": "FC St. Pauli",
    "Holstein Kiel": "Holstein Kiel",
    # 2. Bundesliga
    "Braunschweig": "Eintracht Braunschweig",
    "Greuther Furth": "SpVgg Greuther Fürth",
    "Hamburg": "Hamburger SV",
    "Magdeburg": "1. FC Magdeburg",
    "Nurnberg": "1. FC Nürnberg",
    "Osnabruck": "VfL Osnabrück",
    "Paderborn": "SC Paderborn 07",
    "Regensburg": "SSV Jahn Regensburg",
    "Ulm": "SSV Ulm 1846",
    "Wehen": "SV Wehen",
    "Elversberg": "SV Elversberg",
    "Fortuna Dusseldorf": "Fortuna Düsseldorf",
    "Hannover": "Hannover 96",
    "Karlsruhe": "Karlsruher SC",
    # La Liga
    "Ath Madrid": "Atletico Madrid",
    "Ath Bilbao": "Athletic Club",
    "Betis": "Real Betis",
    "Sociedad": "Real Sociedad",
    "Vallecano": "Rayo Vallecano",
    "Celta": "Celta Vigo",
    "Espanol": "Espanyol",
    "Mallorca": "RCD Mallorca",
    "Las Palmas": "UD Las Palmas",
    "Alaves": "Deportivo Alavés",
    "Leganes": "CD Leganés",
    "Valladolid": "Real Valladolid",
    "Granada": "Granada CF",
    "Castellon": "Castellón",
    # La Liga 2
    "Ferrol": "Racing Ferrol",
    "La Coruna": "Deportivo La Coruna",
    "Santander": "Racing Santander",
    "Sp Gijon": "Sporting Gijon",
    # Serie A
    "Inter": "Inter Milan",
    "Milan": "AC Milan",
    "AC Milan": "AC Milan",
    "Roma": "AS Roma",
    "Lazio": "SS Lazio",
    "Napoli": "SSC Napoli",
    "Atalanta": "Atalanta",
    "Juventus": "Juventus",
    "Fiorentina": "ACF Fiorentina",
    "Verona": "Hellas Verona",
    "Monza": "AC Monza",
    "Cagliari": "Cagliari",
    "Parma": "Parma Calcio 1913",
    "Como": "Como 1907",
    "Venezia": "Venezia FC",
    "Genoa": "Genoa CFC",
    "Torino": "Torino FC",
    "Udinese": "Udinese Calcio",
    "Empoli": "FC Empoli",
    "Lecce": "US Lecce",
    "Salernitana": "US Salernitana 1919",
    "Frosinone": "Frosinone Calcio",
    "Sassuolo": "US Sassuolo",
    # Ligue 1
    "Paris SG": "Paris Saint Germain",
    "PSG": "Paris Saint Germain",
    "Marseille": "Olympique Marseille",
    "Lyon": "Olympique Lyonnais",
    "Monaco": "AS Monaco",
    "Lille": "Lille OSC",
    "Nice": "OGC Nice",
    "Lens": "RC Lens",
    "Rennes": "Stade Rennais",
    "Strasbourg": "RC Strasbourg Alsace",
    "Nantes": "FC Nantes",
    "Reims": "Stade de Reims",
    "Montpellier": "Montpellier HSC",
    "Brest": "Stade Brestois 29",
    "Toulouse": "Toulouse FC",
    "Le Havre": "Le Havre AC",
    "Metz": "FC Metz",
    "Clermont": "Clermont Foot 63",
    "Lorient": "FC Lorient",
    "Angers": "Angers SCO",
    "St Etienne": "AS Saint-Étienne",
    "Auxerre": "AJ Auxerre",
    # Ligue 2
    "Pau FC": "PAU",
    "Quevilly Rouen": "Quevilly",
    "Red Star": "RED Star FC 93",
    "Troyes": "Estac Troyes",
    # Eredivisie
    "Ajax": "AFC Ajax",
    "PSV Eindhoven": "PSV",
    "Feyenoord": "Feyenoord Rotterdam",
    "AZ Alkmaar": "AZ",
    "Twente": "FC Twente",
    "Sparta Rotterdam": "Sparta Rotterdam",
    "Heerenveen": "SC Heerenveen",
    "Utrecht": "FC Utrecht",
    "Groningen": "FC Groningen",
    "Zwolle": "PEC Zwolle",
    "For Sittard": "Fortuna Sittard",
    "Sittard": "Fortuna Sittard",
    "Nijmegen": "NEC Nijmegen",
    "Go Ahead Eagles": "Go Ahead Eagles",
    "Waalwijk": "RKC Waalwijk",
    "Volendam": "FC Volendam",
    "Emmen": "FC Emmen",
    "Excelsior": "SBV Excelsior",
    "NEC": "N.E.C. Nijmegen",
    "Heracles": "Heracles Almelo",
    "Almere City": "Almere City FC",
    "NAC Breda": "NAC Breda",
    "Willem II": "Willem II Tilburg",
    # Portuguese
    "Lisbon": "Sporting CP",
    "Sp Lisbon": "Sporting CP",
    "Sporting": "Sporting CP",
    "Porto": "FC Porto",
    "Benfica": "SL Benfica",
    "Sp Braga": "SC Braga",
    "Braga": "SC Braga",
    "Guimaraes": "Vitória SC",
    "Gil Vicente": "Gil Vicente FC",
    # Belgian
    "Club Brugge": "Club Brugge KV",
    "Anderlecht": "Anderlecht",
    "Genk": "KRC Genk",
    "Antwerp": "Royal Antwerp",
    "Standard": "Standard Liège",
    "Gent": "KAA Gent",
    "Charleroi": "Sporting Charleroi",
    "St Truiden": "St. Truiden",
    "St. Gilloise": "Union St. Gilloise",
    "Mechelen": "KV Mechelen",
    "Cercle Brugge": "Cercle Brugge",
    "Kortrijk": "KV Kortrijk",
    "Westerlo": "KVC Westerlo",
    "Union St. Gilloise": "Union St. Gilloise",
    "OH Leuven": "OH Leuven",
    "Oud-Heverlee Leuven": "OH Leuven",
    "Eupen": "AS Eupen",
    "RWD Molenbeek": "RWDM",
    # Turkish
    "Galatasaray": "Galatasaray",
    "Fenerbahce": "Fenerbahçe",
    "Besiktas": "Beşiktaş",
    "Trabzonspor": "Trabzonspor",
    "Istanbul Basaksehir": "İstanbul Başakşehir",
    "Buyuksehyr": "Başakşehir",
    "Ad. Demirspor": "Adana Demirspor",
    "Ankaragucu": "Ankaragücü",
    "Gaziantep": "Gaziantep FK",
    "Istanbulspor": "İstanbulspor",
    "Kasimpasa": "Kasımpaşa",
    "Antalyaspor": "Antalyaspor",
    "Sivasspor": "Sivasspor",
    "Konyaspor": "Konyaspor",
    "Rizespor": "Çaykur Rizespor",
    "Gaziantep FK": "Gaziantep FK",
    "Kayserispor": "Kayserispor",
    "Hatayspor": "Hatayspor",
    "Samsunspor": "Samsunspor",
    "Pendikspor": "Pendikspor",
    "Bodrum FK": "Bodrum FK",
    "Bodrumspor": "Bodrum FK",
    "Eyupspor": "Eyüpspor",
    "Goztepe": "Göztepe",
    "Goztep": "Göztepe",
    "Karagumruk": "Fatih Karagümrük",
    # Scottish
    "Celtic": "Celtic",
    "Rangers": "Rangers",
    "Aberdeen": "Aberdeen",
    "Hearts": "Heart of Midlothian",
    "Hibs": "Hibernian",
    "Hibernian": "Hibernian",
    "Kilmarnock": "Kilmarnock",
    "St Mirren": "St Mirren",
    "St Johnstone": "St Johnstone",
    "Motherwell": "Motherwell",
    "Dundee": "Dundee FC",
    "Ross County": "Ross County",
    "Dundee United": "Dundee United",
}


def _current_season_code() -> str:
    """Return football-data season code for the current season (e.g. '2425')."""
    now = datetime.now(timezone.utc)
    # Season starts in August: if month >= 8, season = thisYear/nextYear
    if now.month >= 8:
        return f"{now.year % 100:02d}{(now.year + 1) % 100:02d}"
    else:
        return f"{(now.year - 1) % 100:02d}{now.year % 100:02d}"


async def sync_footballdata_odds(session_factory: async_sessionmaker) -> dict:
    """
    Download current-season CSVs from football-data.co.uk and import
    Pinnacle closing odds for fixtures missing them.

    Returns summary dict with counts.
    """
    season = _current_season_code()
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        # Build team lookup
        result = await session.execute(text("SELECT id, name FROM teams"))
        lookup = {}
        all_names = []
        for row in result:
            lookup[row[1].lower()] = row[0]
            stripped = row[1].lower().replace("fc ", "").replace(" fc", "")
            if stripped != row[1].lower():
                lookup[stripped] = row[0]
            all_names.append(row[1])

        # Existing Pinnacle fixtures
        existing = set()
        result = await session.execute(text(
            "SELECT DISTINCT fixture_id FROM odds WHERE bookmaker_name = 'Pinnacle'"
        ))
        for row in result:
            existing.add(row[0])

        logger.info("Football-data sync: season=%s, %d fixtures already have Pinnacle odds",
                     season, len(existing))

        stats = {
            "csv_rows": 0, "team_fail": 0, "not_found": 0,
            "already_has": 0, "no_data": 0, "imported": 0, "odds_rows": 0,
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            for league_id, info in LEAGUE_MAP.items():
                url = f"{BASE_URL}/{season}/{info['code']}.csv"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning("Football-data %s %s: HTTP %d", info["name"], season, resp.status_code)
                        continue
                except Exception as exc:
                    logger.error("Football-data %s %s: %s", info["name"], season, exc)
                    continue

                reader = csv.DictReader(StringIO(resp.text))
                rows = [r for r in reader if r.get("HomeTeam")]
                league_imported = 0

                for row in rows:
                    stats["csv_rows"] += 1
                    home_fd = row.get("HomeTeam", "").strip()
                    away_fd = row.get("AwayTeam", "").strip()
                    date_str = row.get("Date", "").strip()

                    if not home_fd or not away_fd or not date_str:
                        continue

                    home_id = _resolve_team(home_fd, lookup, all_names)
                    away_id = _resolve_team(away_fd, lookup, all_names)
                    if not home_id or not away_id:
                        stats["team_fail"] += 1
                        continue

                    try:
                        match_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                    except ValueError:
                        continue

                    candidates = await session.execute(
                        select(Fixture).where(
                            Fixture.league_id == league_id,
                            Fixture.date >= match_date - timedelta(days=1),
                            Fixture.date <= match_date + timedelta(days=1),
                            Fixture.home_team_id == home_id,
                            Fixture.away_team_id == away_id,
                        )
                    )
                    fixture = candidates.scalars().first()
                    if not fixture:
                        stats["not_found"] += 1
                        continue

                    if fixture.id in existing:
                        stats["already_has"] += 1
                        continue

                    odds_rows = _extract_odds(row, fixture.id, now)
                    if not odds_rows:
                        stats["no_data"] += 1
                        continue

                    session.add_all(odds_rows)
                    stats["imported"] += 1
                    stats["odds_rows"] += len(odds_rows)
                    league_imported += 1
                    existing.add(fixture.id)

                await session.commit()
                if league_imported > 0:
                    logger.info("Football-data %s %s: %d fixtures imported",
                                info["name"], season, league_imported)

    logger.info("Football-data sync complete: %d fixtures, %d odds rows imported",
                stats["imported"], stats["odds_rows"])
    return stats


def _resolve_team(fd_name: str, lookup: dict, all_names: list) -> int | None:
    """Resolve football-data team name to DB team_id."""
    if fd_name in SKIP_TEAMS:
        return None
    if fd_name in MANUAL_OVERRIDES:
        override = MANUAL_OVERRIDES[fd_name]
        tid = lookup.get(override.lower())
        if tid:
            return tid
        best = process.extractOne(override, all_names, scorer=fuzz.token_sort_ratio)
        if best and best[1] >= 85:
            return lookup.get(best[0].lower())
    tid = lookup.get(fd_name.lower())
    if tid:
        return tid
    best = process.extractOne(fd_name, all_names, scorer=fuzz.token_sort_ratio)
    if best and best[1] >= 80:
        return lookup.get(best[0].lower())
    return None


def _extract_odds(row: dict, fixture_id: int, now: datetime) -> list[Odds]:
    """Extract Pinnacle odds from a CSV row. Returns list of Odds objects."""
    psh = row.get("PSH", "").strip()
    psd = row.get("PSD", "").strip()
    psa = row.get("PSA", "").strip()

    if not psh or not psd or not psa:
        return []

    try:
        psh_f, psd_f, psa_f = float(psh), float(psd), float(psa)
    except ValueError:
        return []

    odds_rows = []

    # 1X2
    for label, price in [("Home", psh_f), ("Draw", psd_f), ("Away", psa_f)]:
        if price > 1.0:
            odds_rows.append(Odds(
                fixture_id=fixture_id, market="1x2", label=label,
                value=price, implied_probability=round(1.0 / price, 6),
                bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
            ))

    # DC (derived)
    if psh_f > 1.0 and psd_f > 1.0 and psa_f > 1.0:
        for label, prob in [
            ("1X", (1/psh_f) + (1/psd_f)),
            ("12", (1/psh_f) + (1/psa_f)),
            ("X2", (1/psd_f) + (1/psa_f)),
        ]:
            if prob > 0:
                odds_rows.append(Odds(
                    fixture_id=fixture_id, market="dc", label=label,
                    value=round(1 / prob, 3), implied_probability=round(prob, 6),
                    bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                ))

    # O/U 2.5
    pou_over = row.get("P>2.5", "").strip()
    pou_under = row.get("P<2.5", "").strip()
    if pou_over and pou_under:
        try:
            over_f, under_f = float(pou_over), float(pou_under)
            if over_f > 1.0:
                odds_rows.append(Odds(
                    fixture_id=fixture_id, market="ou25", label="Over 2.5",
                    value=over_f, implied_probability=round(1.0 / over_f, 6),
                    bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                ))
            if under_f > 1.0:
                odds_rows.append(Odds(
                    fixture_id=fixture_id, market="ou25", label="Under 2.5",
                    value=under_f, implied_probability=round(1.0 / under_f, 6),
                    bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                ))
        except ValueError:
            pass

    return odds_rows
