import logging
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.fixture import Fixture
from app.models.fixture_statistics import FixtureStatistics
from app.models.head_to_head import HeadToHead
from app.models.injury import Injury
from app.models.league import League
from app.models.odds import Odds
from app.models.standing import Standing
from app.models.team import Team
from app.models.team_last20 import TeamLast20
from app.services.api_football import APIFootballClient
from app.services.league_config import get_active_league_ids

_ACTIVE_IDS = set(get_active_league_ids())

logger = logging.getLogger(__name__)

# Map API-Football bet names → our market codes + label normalization
MARKET_MAP = {
    "Match Winner": {
        "code": "1x2",
        "labels": {"Home": "Home", "Draw": "Draw", "Away": "Away"},
    },
    "Goals Over/Under": {
        "code": "ou25",
        # We only keep the 2.5 line
        "labels": {"Over 2.5": "Over 2.5", "Under 2.5": "Under 2.5"},
    },
    "Both Teams Score": {
        "code": "btts",
        "labels": {"Yes": "Yes", "No": "No"},
    },
    "Double Chance": {
        "code": "dc",
        "labels": {"Home/Draw": "1X", "Home/Away": "12", "Draw/Away": "X2"},
    },
    "HT/FT Double": {
        "code": "htft",
        "labels": {
            "1/1": "1/1", "1/X": "1/X", "1/2": "1/2",
            "X/1": "X/1", "X/X": "X/X", "X/2": "X/2",
            "2/1": "2/1", "2/X": "2/X", "2/2": "2/2",
        },
    },
}

# Stat type name → our column name
STAT_MAP = {
    "Shots on Goal": "shots_on_goal",
    "Shots off Goal": "shots_off_goal",
    "Total Shots": "total_shots",
    "Blocked Shots": "blocked_shots",
    "Shots insidebox": "shots_insidebox",
    "Shots outsidebox": "shots_outsidebox",
    "Fouls": "fouls",
    "Corner Kicks": "corner_kicks",
    "Offsides": "offsides",
    "Ball Possession": "ball_possession",
    "Yellow Cards": "yellow_cards",
    "Red Cards": "red_cards",
    "Goalkeeper Saves": "goalkeeper_saves",
    "Total passes": "total_passes",
    "Passes accurate": "passes_accurate",
    "Passes %": "passes_pct",
    "expected_goals": "expected_goals",
}


def _parse_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_float(val) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).rstrip("%")
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class DataSyncService:
    """Maps API-Football responses to DB models and upserts."""

    def __init__(self, session_factory: async_sessionmaker, client: APIFootballClient):
        self.session_factory = session_factory
        self.client = client

    # ── Leagues ──────────────────────────────────────────────

    async def sync_leagues(self) -> int:
        """Fetch all leagues from API, upsert into DB. Returns count upserted."""
        raw = await self.client.get_leagues()
        count = 0

        async with self.session_factory() as session:
            for item in raw:
                lg = item.get("league", {})
                country = item.get("country", {})
                seasons = item.get("seasons", [])

                # Find current season
                current_season = None
                coverage = {}
                for s in seasons:
                    if s.get("current"):
                        current_season = s.get("year")
                        coverage = s.get("coverage", {})
                        break
                if current_season is None and seasons:
                    current_season = seasons[-1].get("year", 0)

                league_id = lg.get("id")
                if not league_id:
                    continue

                is_target = league_id in _ACTIVE_IDS
                fixtures_cov = coverage.get("fixtures", {})
                stats_events = fixtures_cov.get("statistics_fixtures", False)

                vals = {
                    "id": league_id,
                    "name": lg.get("name", ""),
                    "country": country.get("name", ""),
                    "country_code": country.get("code", "") or "",
                    "season": current_season or 0,
                    "type": lg.get("type", "League"),
                    "logo_url": lg.get("logo"),
                    "has_standings": bool(coverage.get("standings", False)),
                    "has_statistics": bool(stats_events),
                    "has_odds": bool(coverage.get("odds", False)),
                    "has_injuries": bool(coverage.get("injuries", False)),
                    "has_predictions": bool(coverage.get("predictions", False)),
                    "is_active": is_target,
                }

                stmt = pg_insert(League).values(**vals)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={k: v for k, v in vals.items() if k != "id"},
                )
                await session.execute(stmt)
                count += 1

            await session.commit()

        logger.info("Synced %d leagues (%d target)", count, len(_ACTIVE_IDS))
        return count

    # ── Teams (helper) ───────────────────────────────────────

    async def _ensure_team(self, session: AsyncSession, team_data: dict, league_id: int) -> int:
        """Upsert a team from API fixture/team data. Returns team_id."""
        team_id = team_data["id"]
        vals = {
            "id": team_id,
            "name": team_data.get("name", ""),
            "code": None,
            "league_id": league_id,
            "country": "",
            "logo_url": team_data.get("logo"),
        }
        stmt = pg_insert(Team).values(**vals)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"name": vals["name"], "logo_url": vals["logo_url"]},
        )
        await session.execute(stmt)
        return team_id

    async def _ensure_league(self, session: AsyncSession, league_data: dict) -> int:
        """Upsert a minimal league record from fixture data. Returns league_id."""
        league_id = league_data["id"]
        vals = {
            "id": league_id,
            "name": league_data.get("name", ""),
            "country": league_data.get("country", ""),
            "country_code": "",  # fixture data has flag URL, not code — set by sync_leagues
            "season": league_data.get("season", 0),
            "type": "League",
            "is_active": league_id in _ACTIVE_IDS,
        }
        stmt = pg_insert(League).values(**vals)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"name": vals["name"], "season": vals["season"]},
        )
        await session.execute(stmt)
        return league_id

    async def _ensure_fixture(self, session: AsyncSession, fx_data: dict) -> int:
        """Upsert a fixture from a full API fixture object. Returns fixture_id."""
        fi = fx_data.get("fixture", {})
        league = fx_data.get("league", {})
        teams = fx_data.get("teams", {})
        goals = fx_data.get("goals", {})
        score = fx_data.get("score", {})

        league_id = await self._ensure_league(session, league)
        await self._ensure_team(session, teams.get("home", {}), league_id)
        await self._ensure_team(session, teams.get("away", {}), league_id)

        fixture_id = fi["id"]
        kickoff = _parse_dt(fi.get("date"))
        fixture_date = kickoff.date() if kickoff else date.today()

        ht = score.get("halftime", {})
        ft = score.get("fulltime", {})
        et = score.get("extratime", {})

        vals = {
            "id": fixture_id,
            "date": fixture_date,
            "kickoff_time": kickoff or datetime.now(timezone.utc),
            "home_team_id": teams["home"]["id"],
            "away_team_id": teams["away"]["id"],
            "league_id": league_id,
            "season": league.get("season", 0),
            "round": league.get("round"),
            "venue": (fi.get("venue") or {}).get("name"),
            "referee": fi.get("referee"),
            "status": (fi.get("status") or {}).get("short", "NS"),
            "score_home_ht": _parse_int(ht.get("home") if ht else None),
            "score_away_ht": _parse_int(ht.get("away") if ht else None),
            "score_home_ft": _parse_int(ft.get("home") if ft else goals.get("home")),
            "score_away_ft": _parse_int(ft.get("away") if ft else goals.get("away")),
            "score_home_et": _parse_int(et.get("home") if et else None),
            "score_away_et": _parse_int(et.get("away") if et else None),
        }

        stmt = pg_insert(Fixture).values(**vals)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={k: v for k, v in vals.items() if k != "id"},
        )
        await session.execute(stmt)
        return fixture_id

    # ── Fixtures ─────────────────────────────────────────────

    async def sync_fixtures_for_date(self, date_str: str) -> int:
        """Fetch all fixtures for a date, filter to active leagues, upsert. Returns count."""
        raw = await self.client.get_fixtures_by_date(date_str)
        count = 0

        async with self.session_factory() as session:
            for fx in raw:
                league_id = fx.get("league", {}).get("id")
                if league_id not in _ACTIVE_IDS:
                    continue
                await self._ensure_fixture(session, fx)
                count += 1
            await session.commit()

        logger.info("Synced %d fixtures for %s", count, date_str)
        return count

    # ── Fixture Statistics ───────────────────────────────────

    async def sync_fixture_statistics(self, fixture_id: int) -> int:
        """Fetch match stats for a fixture, upsert per team. Returns count."""
        raw = await self.client.get_fixture_statistics(fixture_id)
        if not raw:
            return 0

        async with self.session_factory() as session:
            # Delete existing stats for this fixture, then insert fresh
            await session.execute(
                delete(FixtureStatistics).where(FixtureStatistics.fixture_id == fixture_id)
            )

            count = 0
            for team_stats in raw:
                team_id = team_stats.get("team", {}).get("id")
                if not team_id:
                    continue

                stats_list = team_stats.get("statistics", [])
                stat_vals = {}
                for s in stats_list:
                    col = STAT_MAP.get(s.get("type"))
                    if col:
                        val = s.get("value")
                        if col in ("ball_possession", "passes_pct", "expected_goals"):
                            stat_vals[col] = _parse_float(val)
                        else:
                            stat_vals[col] = _parse_int(val)

                row = FixtureStatistics(
                    fixture_id=fixture_id,
                    team_id=team_id,
                    **stat_vals,
                )
                session.add(row)
                count += 1

            await session.commit()

        logger.info("Synced %d stat rows for fixture %d", count, fixture_id)
        return count

    # ── Team Last 20 ─────────────────────────────────────────

    async def sync_team_last20(self, team_id: int, league_id: int, season: int) -> int:
        """
        Fetch last 20 fixtures for a team, compute form weights, upsert.
        Returns count of rows upserted.
        """
        raw = await self.client.get_team_fixtures(team_id, season, last=20)
        if not raw:
            return 0

        # Sort by date descending (most recent first) so index 0 = most recent
        raw.sort(key=lambda x: x.get("fixture", {}).get("date", ""), reverse=True)

        count = 0
        async with self.session_factory() as session:
            for idx, fx in enumerate(raw[:20]):
                fi = fx.get("fixture", {})
                teams = fx.get("teams", {})
                goals = fx.get("goals", {})
                lg = fx.get("league", {})

                fixture_id = fi.get("id")
                if not fixture_id:
                    continue

                # Ensure referenced entities exist
                await self._ensure_fixture(session, fx)

                home_id = teams.get("home", {}).get("id")
                away_id = teams.get("away", {}).get("id")
                is_home = (home_id == team_id)
                opponent_id = away_id if is_home else home_id
                venue = "H" if is_home else "A"

                gf = _parse_int(goals.get("home") if is_home else goals.get("away")) or 0
                ga = _parse_int(goals.get("away") if is_home else goals.get("home")) or 0

                if gf > ga:
                    result = "W"
                elif gf == ga:
                    result = "D"
                else:
                    result = "L"

                kickoff = _parse_dt(fi.get("date"))
                fx_date = kickoff.date() if kickoff else date.today()

                # Form weight: linear decay from 1.0 (index 0) to 0.30 (index 19)
                form_weight = round(1.0 - (idx * 0.7 / 19), 4) if idx < 20 else 0.30

                vals = {
                    "team_id": team_id,
                    "fixture_id": fixture_id,
                    "date": fx_date,
                    "opponent_id": opponent_id,
                    "venue": venue,
                    "goals_for": gf,
                    "goals_against": ga,
                    "xg_for": None,
                    "xg_against": None,
                    "shots_on_target": None,
                    "shots_total": None,
                    "possession": None,
                    "corners": None,
                    "result": result,
                    "form_weight": form_weight,
                    "league_id": lg.get("id", league_id),
                    "season": lg.get("season", season),
                }

                # Try to fill xG / stats from fixture_statistics if available
                stat_row = (await session.execute(
                    select(FixtureStatistics).where(
                        FixtureStatistics.fixture_id == fixture_id,
                        FixtureStatistics.team_id == team_id,
                    )
                )).scalar_one_or_none()

                if stat_row:
                    vals["xg_for"] = stat_row.expected_goals
                    vals["shots_on_target"] = stat_row.shots_on_goal
                    vals["shots_total"] = stat_row.total_shots
                    vals["possession"] = stat_row.ball_possession
                    vals["corners"] = stat_row.corner_kicks

                # Opponent xG for xg_against
                opp_stat_row = (await session.execute(
                    select(FixtureStatistics).where(
                        FixtureStatistics.fixture_id == fixture_id,
                        FixtureStatistics.team_id == opponent_id,
                    )
                )).scalar_one_or_none()
                if opp_stat_row:
                    vals["xg_against"] = opp_stat_row.expected_goals

                # Upsert using the unique constraint (team_id, fixture_id)
                stmt = pg_insert(TeamLast20).values(**vals)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_team_fixture",
                    set_={k: v for k, v in vals.items() if k not in ("team_id", "fixture_id")},
                )
                await session.execute(stmt)
                count += 1

            await session.commit()

        logger.info("Synced %d last20 rows for team %d", count, team_id)
        return count

    # ── Head to Head ─────────────────────────────────────────

    async def sync_head_to_head(self, id1: int, id2: int) -> int:
        """Fetch H2H fixtures, normalize team order, upsert. Returns count."""
        raw = await self.client.get_head_to_head(id1, id2, last=20)
        if not raw:
            return 0

        # Normalize: team1_id is always min, team2_id is always max
        t1 = min(id1, id2)
        t2 = max(id1, id2)

        async with self.session_factory() as session:
            # Delete existing H2H for this pair and re-insert
            await session.execute(
                delete(HeadToHead).where(
                    HeadToHead.team1_id == t1,
                    HeadToHead.team2_id == t2,
                )
            )

            count = 0
            for fx in raw:
                fi = fx.get("fixture", {})
                teams = fx.get("teams", {})
                goals = fx.get("goals", {})
                lg = fx.get("league", {})

                fixture_id = fi.get("id")
                if not fixture_id:
                    continue

                await self._ensure_fixture(session, fx)

                home_id = teams.get("home", {}).get("id")
                away_id = teams.get("away", {}).get("id")
                score_home = _parse_int(goals.get("home")) or 0
                score_away = _parse_int(goals.get("away")) or 0
                total = score_home + score_away

                if score_home > score_away:
                    winner = "home"
                elif score_home < score_away:
                    winner = "away"
                else:
                    winner = "draw"

                kickoff = _parse_dt(fi.get("date"))
                fx_date = kickoff.date() if kickoff else date.today()

                # Look up xG from fixture_statistics for both teams
                home_stats = (await session.execute(
                    select(FixtureStatistics).where(
                        FixtureStatistics.fixture_id == fixture_id,
                        FixtureStatistics.team_id == home_id,
                    )
                )).scalar_one_or_none()
                away_stats = (await session.execute(
                    select(FixtureStatistics).where(
                        FixtureStatistics.fixture_id == fixture_id,
                        FixtureStatistics.team_id == away_id,
                    )
                )).scalar_one_or_none()

                row = HeadToHead(
                    team1_id=t1,
                    team2_id=t2,
                    fixture_id=fixture_id,
                    date=fx_date,
                    home_team_id=home_id,
                    score_home=score_home,
                    score_away=score_away,
                    winner=winner,
                    total_goals=total,
                    xg_home=home_stats.expected_goals if home_stats else None,
                    xg_away=away_stats.expected_goals if away_stats else None,
                    league_id=lg.get("id", 0),
                )
                session.add(row)
                count += 1

            await session.commit()

        logger.info("Synced %d H2H rows for %d vs %d", count, t1, t2)
        return count

    # ── Odds ─────────────────────────────────────────────────

    async def sync_odds(self, fixture_id: int) -> int:
        """
        Fetch odds from all bookmakers, parse target markets, upsert.
        Returns count of odds rows inserted.
        """
        raw = await self.client.get_odds(fixture_id)
        if not raw:
            return 0

        now = datetime.now(timezone.utc)

        async with self.session_factory() as session:
            # Delete existing odds for this fixture, insert fresh
            await session.execute(
                delete(Odds).where(Odds.fixture_id == fixture_id)
            )

            count = 0
            for entry in raw:
                bookmakers = entry.get("bookmakers", [])
                for bk in bookmakers:
                    bk_id = bk.get("id", 0)
                    bk_name = bk.get("name", "")

                    for bet in bk.get("bets", []):
                        bet_name = bet.get("name", "")
                        mapping = MARKET_MAP.get(bet_name)
                        if not mapping:
                            continue

                        market_code = mapping["code"]
                        label_map = mapping["labels"]

                        for v in bet.get("values", []):
                            raw_label = str(v.get("value", ""))
                            our_label = label_map.get(raw_label)
                            if our_label is None:
                                continue

                            try:
                                odd_val = float(v.get("odd", 0))
                            except (ValueError, TypeError):
                                continue

                            if odd_val <= 1.0:
                                continue

                            row = Odds(
                                fixture_id=fixture_id,
                                bookmaker_id=bk_id,
                                bookmaker_name=bk_name,
                                market=market_code,
                                label=our_label,
                                value=odd_val,
                                implied_probability=round(1.0 / odd_val, 6),
                                fetched_at=now,
                            )
                            session.add(row)
                            count += 1

            await session.commit()

        logger.info("Synced %d odds rows for fixture %d", count, fixture_id)
        return count

    # ── Standings ────────────────────────────────────────────

    async def sync_standings(self, league_id: int, season: int) -> int:
        """Fetch league standings, upsert. Returns count."""
        raw = await self.client.get_standings(league_id, season)
        if not raw:
            return 0

        now = datetime.now(timezone.utc)

        async with self.session_factory() as session:
            # Delete existing standings for this league+season, insert fresh
            await session.execute(
                delete(Standing).where(
                    Standing.league_id == league_id,
                    Standing.season == season,
                )
            )

            count = 0
            for entry in raw:
                groups = entry.get("league", {}).get("standings", [])
                for group in groups:
                    for row_data in group:
                        team_info = row_data.get("team", {})
                        team_id = team_info.get("id")
                        if not team_id:
                            continue

                        # Ensure team exists
                        await self._ensure_team(session, team_info, league_id)

                        all_stats = row_data.get("all", {})
                        all_goals = all_stats.get("goals", {})
                        home = row_data.get("home", {})
                        home_goals = home.get("goals", {})
                        away = row_data.get("away", {})
                        away_goals = away.get("goals", {})

                        row = Standing(
                            league_id=league_id,
                            season=season,
                            team_id=team_id,
                            rank=row_data.get("rank", 0),
                            points=row_data.get("points", 0),
                            played=all_stats.get("played", 0),
                            won=all_stats.get("win", 0),
                            drawn=all_stats.get("draw", 0),
                            lost=all_stats.get("lose", 0),
                            goals_for=all_goals.get("for", 0),
                            goals_against=all_goals.get("against", 0),
                            goal_diff=row_data.get("goalsDiff", 0),
                            form=row_data.get("form"),
                            home_played=home.get("played", 0),
                            home_won=home.get("win", 0),
                            home_drawn=home.get("draw", 0),
                            home_lost=home.get("lose", 0),
                            home_gf=home_goals.get("for", 0),
                            home_ga=home_goals.get("against", 0),
                            away_played=away.get("played", 0),
                            away_won=away.get("win", 0),
                            away_drawn=away.get("draw", 0),
                            away_lost=away.get("lose", 0),
                            away_gf=away_goals.get("for", 0),
                            away_ga=away_goals.get("against", 0),
                            last_updated=now,
                        )
                        session.add(row)
                        count += 1

            await session.commit()

        logger.info("Synced %d standing rows for league %d season %d", count, league_id, season)
        return count

    # ── Injuries ─────────────────────────────────────────────

    async def sync_injuries(self, fixture_id: int) -> int:
        """Fetch injuries/suspensions for a fixture, upsert. Returns count."""
        raw = await self.client.get_injuries(fixture_id)
        if not raw:
            return 0

        async with self.session_factory() as session:
            # Delete existing injuries for this fixture, insert fresh
            await session.execute(
                delete(Injury).where(Injury.fixture_id == fixture_id)
            )

            count = 0
            for item in raw:
                player = item.get("player", {})
                team = item.get("team", {})
                player_id = player.get("id")
                team_id = team.get("id")
                if not player_id or not team_id:
                    continue

                row = Injury(
                    fixture_id=fixture_id,
                    team_id=team_id,
                    player_id=player_id,
                    player_name=player.get("name", "Unknown"),
                    type=player.get("type", "Unknown"),
                    reason=player.get("reason"),
                )
                session.add(row)
                count += 1

            await session.commit()

        logger.info("Synced %d injuries for fixture %d", count, fixture_id)
        return count

    # ── Backfill ─────────────────────────────────────────────

    async def backfill_league(self, league_id: int, season: int) -> int:
        """
        Get ALL completed fixtures for a league+season.
        For each: upsert fixture, sync stats, build team_last20.
        Rate limited by the API client. Returns fixture count.
        """
        raw = await self.client.get_fixtures_by_league_season(league_id, season, status="FT")
        logger.info("Backfill: %d finished fixtures for league %d season %d", len(raw), league_id, season)

        count = 0
        async with self.session_factory() as session:
            for fx in raw:
                await self._ensure_fixture(session, fx)
                count += 1
                if count % 50 == 0:
                    await session.commit()
                    logger.info("Backfill progress: %d/%d fixtures", count, len(raw))

            await session.commit()

        # Sync stats for each fixture (separate API calls, rate limited)
        for fx in raw:
            fid = fx.get("fixture", {}).get("id")
            if fid:
                try:
                    await self.sync_fixture_statistics(fid)
                except Exception as exc:
                    logger.warning("Failed to sync stats for fixture %d: %s", fid, exc)

        logger.info("Backfill complete: %d fixtures for league %d season %d", count, league_id, season)
        return count
