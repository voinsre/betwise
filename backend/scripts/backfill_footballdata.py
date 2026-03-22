"""
Football-data.co.uk Historical Odds Backfill

Phase 1: Explore CSV structure
Phase 2: Team name matching
Phase 3: Import Pinnacle closing odds into DB

Usage:
  python scripts/backfill_footballdata.py explore     # Phase 1
  python scripts/backfill_footballdata.py match        # Phase 2
  python scripts/backfill_footballdata.py import       # Phase 3
"""
import asyncio
import csv
import sys
import os
from io import StringIO
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise")

import httpx

# ═══════════════════════════════════════════════════
# LEAGUE MAP: our league ID -> football-data.co.uk code
# ═══════════════════════════════════════════════════
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

SEASONS = ["2324", "2425"]

BASE_URL = "https://www.football-data.co.uk/mmz4281"

# Teams to skip (B teams, etc. - no match in our DB)
SKIP_TEAMS = {
    "Villarreal B",
}

# ═══════════════════════════════════════════════════
# MANUAL OVERRIDES: football-data name -> our API-Football name
# ═══════════════════════════════════════════════════
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
    "Hoffenheim": "TSG Hoffenheim",
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
    "Hoffenheim": "1899 Hoffenheim",

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


# ═══════════════════════════════════════════════════
# PHASE 1: Explore CSV structure
# ═══════════════════════════════════════════════════

async def explore():
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        url = f"{BASE_URL}/2425/E0.csv"
        resp = await client.get(url)
        print(f"Status: {resp.status_code}")
        print(f"Content length: {len(resp.text)}")

        # Parse CSV
        reader = csv.DictReader(StringIO(resp.text))
        headers = reader.fieldnames
        print(f"\nAll columns ({len(headers)}):")
        for h in headers:
            print(f"  {h}")

        # Show first 3 rows with Pinnacle columns
        print("\n=== First 3 rows (key columns) ===")
        reader = csv.DictReader(StringIO(resp.text))
        for i, row in enumerate(reader):
            if i >= 3:
                break
            print(f"\nRow {i+1}:")
            print(f"  Date: {row.get('Date', 'N/A')}")
            print(f"  HomeTeam: {row.get('HomeTeam', 'N/A')}")
            print(f"  AwayTeam: {row.get('AwayTeam', 'N/A')}")
            print(f"  FTHG/FTAG: {row.get('FTHG', 'N/A')}-{row.get('FTAG', 'N/A')}")
            print(f"  Pinnacle 1X2: H={row.get('PSH', 'N/A')} D={row.get('PSD', 'N/A')} A={row.get('PSA', 'N/A')}")
            print(f"  Pinnacle O/U 2.5: O={row.get('P>2.5', 'N/A')} U={row.get('P<2.5', 'N/A')}")

        # Count rows and Pinnacle coverage
        reader = csv.DictReader(StringIO(resp.text))
        total = 0
        has_pinnacle = 0
        has_ou25 = 0
        for row in reader:
            total += 1
            if row.get('PSH') and row.get('PSH').strip():
                has_pinnacle += 1
            if row.get('P>2.5') and row.get('P>2.5').strip():
                has_ou25 += 1
        print(f"\nTotal matches: {total}")
        print(f"With Pinnacle 1X2: {has_pinnacle} ({round(has_pinnacle/total*100)}%)")
        print(f"With Pinnacle O/U 2.5: {has_ou25} ({round(has_ou25/total*100)}%)")


# ═══════════════════════════════════════════════════
# SHARED: Download all CSVs
# ═══════════════════════════════════════════════════

async def download_all_csvs():
    """Download all CSVs and return {(league_id, season): [rows]}"""
    all_data = {}
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for league_id, info in LEAGUE_MAP.items():
            code = info["code"]
            for season in SEASONS:
                url = f"{BASE_URL}/{season}/{code}.csv"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        print(f"  MISS {info['name']} {season}: HTTP {resp.status_code}")
                        continue
                    reader = csv.DictReader(StringIO(resp.text))
                    rows = [r for r in reader if r.get("HomeTeam")]
                    all_data[(league_id, season)] = rows
                    print(f"  OK   {info['name']} {season}: {len(rows)} matches")
                except Exception as e:
                    print(f"  ERR  {info['name']} {season}: {e}")
    return all_data


# ═══════════════════════════════════════════════════
# PHASE 2: Team name matching
# ═══════════════════════════════════════════════════

async def match_teams():
    from rapidfuzz import fuzz, process
    from sqlalchemy import text
    from app.database import async_session

    print("Downloading CSVs...")
    all_data = await download_all_csvs()

    async with async_session() as session:
        # Build lookup: lowercase team name -> team_id
        result = await session.execute(text("SELECT id, name FROM teams"))
        lookup = {}
        all_names = []
        for row in result:
            lookup[row[1].lower()] = row[0]
            # Also index without "FC" prefix/suffix
            stripped = row[1].lower().replace("fc ", "").replace(" fc", "")
            if stripped != row[1].lower():
                lookup[stripped] = row[0]
            all_names.append(row[1])

        def match_team(fd_name):
            """Match football-data name to our DB. Returns (our_name, our_id, method)."""
            # 0. Skip list
            if fd_name in SKIP_TEAMS:
                return None, None, "skipped"

            # 1. Manual override
            if fd_name in MANUAL_OVERRIDES:
                override_name = MANUAL_OVERRIDES[fd_name]
                tid = lookup.get(override_name.lower())
                if tid:
                    return override_name, tid, "override"
                # Override name might not exactly match DB - fuzzy it
                best = process.extractOne(override_name, all_names, scorer=fuzz.token_sort_ratio)
                if best and best[1] >= 85:
                    tid = lookup.get(best[0].lower())
                    if tid:
                        return best[0], tid, "override->fuzzy"

            # 2. Exact match (case-insensitive)
            tid = lookup.get(fd_name.lower())
            if tid:
                return fd_name, tid, "exact"

            # 3. Fuzzy match
            best = process.extractOne(fd_name, all_names, scorer=fuzz.token_sort_ratio)
            if best and best[1] >= 80:
                tid = lookup.get(best[0].lower())
                if tid:
                    return best[0], tid, f"fuzzy({best[1]})"

            return None, None, "unmatched"

        # Collect ALL unique team names from CSVs
        team_names_by_league = defaultdict(set)
        for (league_id, season), rows in all_data.items():
            for row in rows:
                home = row.get("HomeTeam", "").strip()
                away = row.get("AwayTeam", "").strip()
                if home:
                    team_names_by_league[league_id].add(home)
                if away:
                    team_names_by_league[league_id].add(away)

        # Match each team
        total_teams = 0
        matched = 0
        unmatched_list = []
        suspicious_list = []

        print("\n" + "=" * 70)
        print("TEAM MATCHING REPORT")
        print("=" * 70)

        for league_id in sorted(team_names_by_league.keys()):
            league_name = LEAGUE_MAP[league_id]["name"]
            teams = sorted(team_names_by_league[league_id])
            print(f"\n--- {league_name} ({len(teams)} teams) ---")

            for fd_name in teams:
                total_teams += 1
                our_name, our_id, method = match_team(fd_name)

                if method == "skipped":
                    print(f"  -- '{fd_name}' -> SKIPPED (B team)")
                elif our_name:
                    matched += 1
                    flag = "OK"
                    if "fuzzy" in method and not method.startswith("override"):
                        suspicious_list.append((fd_name, our_name, method, league_name))
                        flag = "??"
                    print(f"  {flag} '{fd_name}' -> '{our_name}' (id:{our_id}) [{method}]")
                else:
                    unmatched_list.append((fd_name, league_name))
                    print(f"  XX '{fd_name}' -> NO MATCH [{method}]")

        # Summary
        print(f"\n{'='*70}")
        pct = round(matched/total_teams*100, 1) if total_teams else 0
        print(f"SUMMARY: {matched}/{total_teams} matched ({pct}%)")
        print(f"{'='*70}")

        if unmatched_list:
            print(f"\nXX UNMATCHED ({len(unmatched_list)}):")
            for name, league in unmatched_list:
                print(f"  '{name}' ({league})")

        if suspicious_list:
            print(f"\n?? SUSPICIOUS FUZZY MATCHES ({len(suspicious_list)}) -- verify these:")
            for fd_name, our_name, method, league in suspicious_list:
                print(f"  '{fd_name}' -> '{our_name}' [{method}] ({league})")

        # Pinnacle coverage check
        print(f"\n{'='*70}")
        print("PINNACLE ODDS COVERAGE IN CSVs")
        print(f"{'='*70}")
        total_matches = 0
        has_pinnacle_1x2 = 0
        has_pinnacle_ou25 = 0
        for (league_id, season), rows in sorted(all_data.items()):
            league_name = LEAGUE_MAP[league_id]["name"]
            lm = 0
            lp1x2 = 0
            lpou = 0
            for row in rows:
                lm += 1
                if row.get("PSH", "").strip():
                    lp1x2 += 1
                if row.get("P>2.5", "").strip():
                    lpou += 1
            total_matches += lm
            has_pinnacle_1x2 += lp1x2
            has_pinnacle_ou25 += lpou
            print(f"  {league_name} {season}: {lm} matches, "
                  f"Pinnacle 1X2: {lp1x2} ({round(lp1x2/lm*100) if lm else 0}%), "
                  f"Pinnacle O/U 2.5: {lpou} ({round(lpou/lm*100) if lm else 0}%)")

        print(f"\nTotal: {total_matches} matches, "
              f"Pinnacle 1X2: {has_pinnacle_1x2}, "
              f"Pinnacle O/U 2.5: {has_pinnacle_ou25}")


# ═══════════════════════════════════════════════════
# PHASE 3: Import odds
# ═══════════════════════════════════════════════════

async def import_odds(single_league_id: int | None = None):
    from rapidfuzz import fuzz, process
    from sqlalchemy import select, text
    from app.database import async_session
    from app.models.fixture import Fixture
    from app.models.odds import Odds

    now = datetime.now(timezone.utc)

    # Download CSVs (filter to single league if requested)
    print("Downloading CSVs...")
    all_data = await download_all_csvs()
    if single_league_id:
        all_data = {k: v for k, v in all_data.items() if k[0] == single_league_id}

    async with async_session() as session:
        # Build team name -> team_id lookup (same logic as Phase 2)
        result = await session.execute(text("SELECT id, name FROM teams"))
        lookup = {}
        all_names = []
        for row in result:
            lookup[row[1].lower()] = row[0]
            stripped = row[1].lower().replace("fc ", "").replace(" fc", "")
            if stripped != row[1].lower():
                lookup[stripped] = row[0]
            all_names.append(row[1])

        def resolve_team_id(fd_name):
            """Resolve football-data team name to our team_id."""
            if fd_name in SKIP_TEAMS:
                return None
            if fd_name in MANUAL_OVERRIDES:
                override_name = MANUAL_OVERRIDES[fd_name]
                tid = lookup.get(override_name.lower())
                if tid:
                    return tid
                best = process.extractOne(override_name, all_names, scorer=fuzz.token_sort_ratio)
                if best and best[1] >= 85:
                    return lookup.get(best[0].lower())
            tid = lookup.get(fd_name.lower())
            if tid:
                return tid
            best = process.extractOne(fd_name, all_names, scorer=fuzz.token_sort_ratio)
            if best and best[1] >= 80:
                return lookup.get(best[0].lower())
            return None

        # Check which fixtures already have Pinnacle odds
        existing_pinnacle = set()
        result = await session.execute(text(
            "SELECT DISTINCT fixture_id FROM odds WHERE bookmaker_name = 'Pinnacle'"
        ))
        for row in result:
            existing_pinnacle.add(row[0])
        print(f"Fixtures already with Pinnacle odds: {len(existing_pinnacle)}")

        # Stats
        total_csv_rows = 0
        team_resolve_fail = 0
        fixture_not_found = 0
        already_has_odds = 0
        no_pinnacle_data = 0
        odds_imported = 0
        fixtures_imported = 0
        batch_count = 0

        for (league_id, season), rows in sorted(all_data.items()):
            league_name = LEAGUE_MAP[league_id]["name"]
            league_fixtures_imported = 0
            league_odds_imported = 0
            print(f"\n{'='*60}")
            print(f"  {league_name} {season}: {len(rows)} CSV rows")

            for row in rows:
                total_csv_rows += 1
                home_fd = row.get("HomeTeam", "").strip()
                away_fd = row.get("AwayTeam", "").strip()
                date_str = row.get("Date", "").strip()

                if not home_fd or not away_fd or not date_str:
                    continue

                # Resolve team IDs
                home_id = resolve_team_id(home_fd)
                away_id = resolve_team_id(away_fd)
                if not home_id or not away_id:
                    team_resolve_fail += 1
                    continue

                # Parse date (DD/MM/YYYY)
                try:
                    match_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                except ValueError:
                    continue

                # Find our fixture
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
                    fixture_not_found += 1
                    continue

                # Skip if already has Pinnacle odds
                if fixture.id in existing_pinnacle:
                    already_has_odds += 1
                    continue

                # Extract Pinnacle odds from CSV
                psh = row.get("PSH", "").strip()
                psd = row.get("PSD", "").strip()
                psa = row.get("PSA", "").strip()
                pou_over = row.get("P>2.5", "").strip()
                pou_under = row.get("P<2.5", "").strip()

                if not psh or not psd or not psa:
                    no_pinnacle_data += 1
                    continue

                try:
                    psh_f = float(psh)
                    psd_f = float(psd)
                    psa_f = float(psa)
                except ValueError:
                    no_pinnacle_data += 1
                    continue

                odds_rows = []

                # 1X2 market
                for label, price in [("Home", psh_f), ("Draw", psd_f), ("Away", psa_f)]:
                    if price > 1.0:
                        odds_rows.append(Odds(
                            fixture_id=fixture.id,
                            market="1x2",
                            label=label,
                            value=price,
                            implied_probability=round(1.0 / price, 6),
                            bookmaker_name="Pinnacle",
                            bookmaker_id=0,
                            fetched_at=now,
                        ))

                # DC market (derived from 1X2)
                if psh_f > 1.0 and psd_f > 1.0 and psa_f > 1.0:
                    dc_1x_prob = (1/psh_f) + (1/psd_f)
                    dc_12_prob = (1/psh_f) + (1/psa_f)
                    dc_x2_prob = (1/psd_f) + (1/psa_f)

                    if dc_1x_prob > 0:
                        dc_1x = round(1 / dc_1x_prob, 3)
                        odds_rows.append(Odds(
                            fixture_id=fixture.id, market="dc", label="1X",
                            value=dc_1x, implied_probability=round(dc_1x_prob, 6),
                            bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                        ))
                    if dc_12_prob > 0:
                        dc_12 = round(1 / dc_12_prob, 3)
                        odds_rows.append(Odds(
                            fixture_id=fixture.id, market="dc", label="12",
                            value=dc_12, implied_probability=round(dc_12_prob, 6),
                            bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                        ))
                    if dc_x2_prob > 0:
                        dc_x2 = round(1 / dc_x2_prob, 3)
                        odds_rows.append(Odds(
                            fixture_id=fixture.id, market="dc", label="X2",
                            value=dc_x2, implied_probability=round(dc_x2_prob, 6),
                            bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                        ))

                # O/U 2.5 market
                if pou_over and pou_under:
                    try:
                        over_f = float(pou_over)
                        under_f = float(pou_under)
                        if over_f > 1.0:
                            odds_rows.append(Odds(
                                fixture_id=fixture.id, market="ou25", label="Over 2.5",
                                value=over_f, implied_probability=round(1.0 / over_f, 6),
                                bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                            ))
                        if under_f > 1.0:
                            odds_rows.append(Odds(
                                fixture_id=fixture.id, market="ou25", label="Under 2.5",
                                value=under_f, implied_probability=round(1.0 / under_f, 6),
                                bookmaker_name="Pinnacle", bookmaker_id=0, fetched_at=now,
                            ))
                    except ValueError:
                        pass

                if odds_rows:
                    session.add_all(odds_rows)
                    odds_imported += len(odds_rows)
                    league_odds_imported += len(odds_rows)
                    fixtures_imported += 1
                    league_fixtures_imported += 1
                    existing_pinnacle.add(fixture.id)

                # Commit every 500 fixtures
                batch_count += 1
                if batch_count % 500 == 0:
                    await session.commit()
                    print(f"  ... committed ({batch_count} processed, {odds_imported} odds so far)")

                # Progress log every 100 imported fixtures
                if fixtures_imported % 100 == 0 and fixtures_imported > 0 and league_fixtures_imported > 0:
                    print(f"  {league_name}: {league_fixtures_imported} fixtures, "
                          f"{league_odds_imported} odds rows")

            # Commit at end of each league
            await session.commit()
            print(f"  {league_name} {season}: {league_fixtures_imported} fixtures imported, "
                  f"{league_odds_imported} odds rows")

    # Final summary
    print(f"\n{'='*60}")
    print("IMPORT COMPLETE")
    print(f"{'='*60}")
    print(f"Total CSV rows:        {total_csv_rows}")
    print(f"Team resolve fail:     {team_resolve_fail}")
    print(f"Fixture not found:     {fixture_not_found}")
    print(f"Already had odds:      {already_has_odds}")
    print(f"No Pinnacle data:      {no_pinnacle_data}")
    print(f"Fixtures imported:     {fixtures_imported}")
    print(f"Odds rows imported:    {odds_imported}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "explore"
    if cmd == "explore":
        asyncio.run(explore())
    elif cmd == "match":
        asyncio.run(match_teams())
    elif cmd == "import":
        league_id = None
        if "--league" in sys.argv:
            idx = sys.argv.index("--league")
            league_id = int(sys.argv[idx + 1])
        asyncio.run(import_odds(single_league_id=league_id))
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python scripts/backfill_footballdata.py [explore|match|import]")
