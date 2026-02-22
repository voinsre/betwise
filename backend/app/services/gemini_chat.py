"""Gemini chat service with structured function calling — Phase 7.

Uses Google Gemini 2.5 Flash with 5 tool functions that route to
the backend prediction engine and ticket builder for real data.
"""

import json
import logging
from datetime import date, timedelta

import google.generativeai as genai
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import aliased

from app.config import settings
from app.models.fixture import Fixture
from app.models.league import League
from app.models.team import Team
from app.services.live_fixtures import get_upcoming_fixture_ids
from app.services.prediction_engine import PredictionEngine
from app.services.ticket_builder import TicketBuilder

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are BetWise AI, a football betting intelligence assistant. You help users build betting tickets based on AI-powered predictions.

IMPORTANT RULES:
- You NEVER make predictions yourself. All probabilities come from the backend prediction engine.
- You use the provided functions to query predictions, build tickets, and analyze fixtures.
- You explain the model's confidence and edge clearly.
- You always remind users that no prediction is guaranteed and to bet responsibly.
- You present data in a clear, organized format.
- You understand betting terminology: odds, edge, value bet, accumulator/parlay, Kelly criterion.
- When a user asks for a ticket, extract: number of games, target odds (if mentioned), preferred markets, and date.
- Star ratings: ★★★ = confidence 80+, ★★☆ = 65-79, ★☆☆ = 50-64
- When showing predictions, format them as a clear table or list with match, market, selection, odds, edge, and confidence.

BETTING RECOMMENDATION — CRITICAL:
- After showing the analysis, you MUST always give a clear betting recommendation.
- Identify the BEST value bets from the analysis: selections with positive edge and high confidence.
- Structure your recommendation like:
  "🎯 **My recommendation:** [selection] at [odds] — the model sees [edge]% edge with [confidence]% confidence."
- If multiple selections have positive edge, rank them and suggest the top 1-3 picks.
- If NO selections have positive edge, say clearly: "The model doesn't see strong value in this match right now" and suggest the user check other fixtures.
- Always end with a brief risk note: "Remember, no prediction is guaranteed — bet responsibly."
- Be opinionated and decisive. Users want a clear answer, not just raw data.

TEAM SEARCH BEHAVIOR — CRITICAL:
- When a user mentions a team name (e.g. "What should I bet on Roma?", "How about Man United?", "Roma vs Milan"), you MUST immediately:
  1. Call search_fixtures with the team name to find the fixture
  2. Call analyze_fixture with the fixture_id from the search results
  3. Present ALL market predictions (1x2, ou25, btts, etc.) with the full analysis
  4. Give a clear betting recommendation based on the best value selections
- Do NOT ask the user which market they want. Show ALL markets by default.
- Do NOT ask for clarification when the intent is clear. Just find the game and show the analysis.
- Only ask for clarification if search_fixtures returns multiple fixtures on different dates and it's genuinely unclear which one the user means.
- If the team has no fixtures in the next few days, say so clearly and suggest checking a different date.

LIVE AND FINISHED GAMES:
- By default, get_predictions only returns upcoming (not started) fixtures. If the user asks about a live or finished game, use include_all_statuses=true.
- For finished games, clearly note that predictions are retrospective — what the model would have bet before kickoff.
- For live games, note that predictions are pre-match and don't account for in-game events.
- Today's date is {today}.
""".strip()


def _build_tools() -> list:
    """Build the 5 function declarations for Gemini tool calling."""
    return [
        genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name="get_predictions",
                    description="Get predictions for a given date. Can filter by market, minimum confidence, or value bets only.",
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "date": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="Date in YYYY-MM-DD format",
                            ),
                            "market": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="Filter by market: 1x2, ou25, btts, dc, htft",
                            ),
                            "min_confidence": genai.protos.Schema(
                                type=genai.protos.Type.INTEGER,
                                description="Minimum confidence score (0-100)",
                            ),
                            "value_only": genai.protos.Schema(
                                type=genai.protos.Type.BOOLEAN,
                                description="Only return value bets (edge > 2%, confidence >= 60)",
                            ),
                            "include_all_statuses": genai.protos.Schema(
                                type=genai.protos.Type.BOOLEAN,
                                description="If true, include predictions for live and finished fixtures too (not just upcoming). Default false.",
                            ),
                        },
                        required=["date"],
                    ),
                ),
                genai.protos.FunctionDeclaration(
                    name="build_ticket",
                    description="Build an optimized betting ticket with the specified number of games and optional target odds",
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "date": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="Date in YYYY-MM-DD format",
                            ),
                            "num_games": genai.protos.Schema(
                                type=genai.protos.Type.INTEGER,
                                description="Number of games in the ticket",
                            ),
                            "target_odds": genai.protos.Schema(
                                type=genai.protos.Type.NUMBER,
                                description="Target combined odds for the ticket",
                            ),
                            "preferred_markets": genai.protos.Schema(
                                type=genai.protos.Type.ARRAY,
                                items=genai.protos.Schema(type=genai.protos.Type.STRING),
                                description="Preferred markets: 1x2, ou25, btts, dc, htft",
                            ),
                            "min_confidence": genai.protos.Schema(
                                type=genai.protos.Type.INTEGER,
                                description="Minimum confidence score for legs",
                            ),
                        },
                        required=["date", "num_games"],
                    ),
                ),
                genai.protos.FunctionDeclaration(
                    name="analyze_fixture",
                    description="Get deep analysis of a specific fixture including all market predictions, Poisson model output, and value bets",
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "fixture_id": genai.protos.Schema(
                                type=genai.protos.Type.INTEGER,
                                description="The fixture ID to analyze",
                            ),
                        },
                        required=["fixture_id"],
                    ),
                ),
                genai.protos.FunctionDeclaration(
                    name="swap_ticket_game",
                    description="Replace one game in an existing ticket with the next best alternative",
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "ticket_id": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="UUID of the ticket to modify",
                            ),
                            "fixture_id_to_remove": genai.protos.Schema(
                                type=genai.protos.Type.INTEGER,
                                description="Fixture ID of the game to remove",
                            ),
                            "preference": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="'safer' for higher probability replacement, 'riskier' for higher odds",
                            ),
                        },
                        required=["ticket_id", "fixture_id_to_remove"],
                    ),
                ),
                genai.protos.FunctionDeclaration(
                    name="search_fixtures",
                    description=(
                        "Search for fixtures by team name. Returns matching fixtures "
                        "from recent and upcoming days with fixture IDs, team names, "
                        "status, kickoff time, and league. Use this when the user "
                        "mentions a team name and you need to find the fixture ID."
                    ),
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "team_name": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="Team name or partial name to search for (e.g. 'Roma', 'Man United', 'Barcelona')",
                            ),
                            "date": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="Optional center date in YYYY-MM-DD format. Defaults to today. Searches +/- 3 days around this date.",
                            ),
                            "status": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description="Optional status filter: 'upcoming' (not started), 'live', 'finished', or 'all'. Defaults to 'all'.",
                            ),
                        },
                        required=["team_name"],
                    ),
                ),
            ]
        ),
    ]


class GeminiChatService:
    """Gemini 2.0 Flash chat with function calling for BetWise."""

    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory
        self._engine: PredictionEngine | None = None
        self._builder: TicketBuilder | None = None

        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=SYSTEM_PROMPT.format(today=date.today()),
            tools=_build_tools(),
        )

    def _get_engine(self) -> PredictionEngine:
        if self._engine is None:
            self._engine = PredictionEngine(self.session_factory)
            self._engine.load_models()
        return self._engine

    def _get_builder(self) -> TicketBuilder:
        if self._builder is None:
            self._builder = TicketBuilder(self.session_factory, self._get_engine())
        return self._builder

    async def chat(self, user_message: str, history: list[dict]) -> tuple[str, list[dict], dict | None]:
        """
        Process a user message with function calling loop.

        Args:
            user_message: The user's message text
            history: List of previous messages [{role, content}]

        Returns:
            (response_text, updated_history, structured_data)
        """
        # Convert history to Gemini format
        gemini_history = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            gemini_history.append({
                "role": role,
                "parts": [msg.get("content", "")],
            })

        chat_session = self.model.start_chat(history=gemini_history)

        # Send the user message and handle function calls
        response, structured_data = await self._send_with_function_loop(chat_session, user_message)

        # Build updated history
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})
        updated_history.append({"role": "assistant", "content": response})

        return response, updated_history, structured_data

    # Map function names to structured_data types
    _FUNCTION_TYPE_MAP = {
        "get_predictions": "value_bets",
        "build_ticket": "ticket",
        "analyze_fixture": "analysis",
        "swap_ticket_game": "ticket",
        "search_fixtures": "fixtures",
    }

    async def _send_with_function_loop(
        self, chat_session, message: str, max_rounds: int = 5
    ) -> tuple[str, dict | None]:
        """
        Send a message and handle the function calling loop.
        Gemini may call functions multiple times before giving a text response.
        Returns (text_response, structured_data).
        """
        response = chat_session.send_message(message)
        structured_data: dict | None = None

        for _ in range(max_rounds):
            # Check if there's a function call in the response
            func_call = self._extract_function_call(response)
            if func_call is None:
                break

            fn_name, fn_args = func_call
            logger.info("Gemini called function: %s(%s)", fn_name, fn_args)

            # Execute the function
            try:
                result = await self._execute_function(fn_name, fn_args)
            except Exception as e:
                logger.error("Function %s failed: %s", fn_name, e, exc_info=True)
                result = {"error": "Function call failed. Please try again."}

            # Capture structured data from the last successful function call
            if "error" not in result:
                data_type = self._FUNCTION_TYPE_MAP.get(fn_name)
                if data_type:
                    structured_data = {
                        "type": data_type,
                        "function": fn_name,
                        "data": self._make_serializable(result),
                    }

            # Serialize result for Gemini
            result_serializable = self._make_serializable(result)

            # Send the function result back to Gemini
            response = chat_session.send_message(
                genai.protos.Content(
                    parts=[
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=fn_name,
                                response={"result": result_serializable},
                            )
                        )
                    ]
                )
            )

        return self._extract_text(response), structured_data

    def _extract_function_call(self, response) -> tuple[str, dict] | None:
        """Extract function call from a Gemini response, if present."""
        try:
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "function_call") and part.function_call.name:
                        fn_name = part.function_call.name
                        fn_args = dict(part.function_call.args)
                        return fn_name, fn_args
        except (AttributeError, IndexError):
            pass
        return None

    def _extract_text(self, response) -> str:
        """Extract text content from a Gemini response."""
        try:
            return response.text
        except (AttributeError, ValueError):
            try:
                parts = []
                for candidate in response.candidates:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            parts.append(part.text)
                return "\n".join(parts) if parts else "I couldn't generate a response. Please try again."
            except Exception:
                return "I couldn't generate a response. Please try again."

    _VALID_MARKETS = {"1x2", "ou25", "btts", "dc", "htft"}
    _VALID_PREFERENCES = {"safer", "riskier"}

    _TEAM_ALIASES: dict[str, str] = {
        "man united": "Manchester United",
        "man utd": "Manchester United",
        "man city": "Manchester City",
        "barca": "Barcelona",
        "juve": "Juventus",
        "atletico": "Atletico Madrid",
        "atleti": "Atletico Madrid",
        "spurs": "Tottenham",
        "inter": "Inter Milan",
        "psg": "Paris Saint Germain",
        "bayern": "Bayern Munich",
        "dortmund": "Borussia Dortmund",
        "real": "Real Madrid",
        "ac milan": "AC Milan",
        "napoli": "SSC Napoli",
        "roma": "AS Roma",
        "lazio": "SS Lazio",
    }

    _STATUS_GROUPS: dict[str, list[str]] = {
        "upcoming": ["NS", "TBD"],
        "live": ["1H", "2H", "HT", "ET", "BT", "P", "SUSP", "INT"],
        "finished": ["FT", "AET", "PEN"],
    }

    def _safe_parse_date(self, raw: str) -> date:
        """Parse a date string, raising ValueError with a safe message."""
        try:
            return date.fromisoformat(raw[:10])
        except (ValueError, TypeError):
            raise ValueError("Invalid date format — expected YYYY-MM-DD")

    async def _search_fixtures_by_team(
        self,
        team_query: str,
        center_date: date,
        status_filter: str = "all",
    ) -> dict:
        """Search fixtures by team name with ILIKE matching and alias resolution."""
        resolved = self._TEAM_ALIASES.get(team_query.lower().strip(), team_query)
        pattern = f"%{resolved}%"

        start_date = center_date - timedelta(days=3)
        end_date = center_date + timedelta(days=3)

        HomeTeam = aliased(Team)
        AwayTeam = aliased(Team)

        async with self.session_factory() as session:
            q = (
                select(
                    Fixture.id,
                    Fixture.date,
                    Fixture.kickoff_time,
                    Fixture.status,
                    Fixture.score_home_ft,
                    Fixture.score_away_ft,
                    Fixture.score_home_ht,
                    Fixture.score_away_ht,
                    HomeTeam.name.label("home_team"),
                    AwayTeam.name.label("away_team"),
                    League.name.label("league_name"),
                )
                .join(HomeTeam, Fixture.home_team_id == HomeTeam.id)
                .join(AwayTeam, Fixture.away_team_id == AwayTeam.id)
                .join(League, Fixture.league_id == League.id)
                .where(
                    Fixture.date.between(start_date, end_date),
                    or_(
                        HomeTeam.name.ilike(pattern),
                        AwayTeam.name.ilike(pattern),
                    ),
                )
            )

            if status_filter in self._STATUS_GROUPS:
                q = q.where(Fixture.status.in_(self._STATUS_GROUPS[status_filter]))

            q = q.order_by(Fixture.kickoff_time.desc()).limit(10)

            result = await session.execute(q)
            rows = result.all()

        if not rows:
            return {
                "fixtures": [],
                "count": 0,
                "message": f"No fixtures found for '{team_query}' between {start_date} and {end_date}. Try a different date or team name.",
            }

        fixtures = []
        for row in rows:
            score = None
            if row.score_home_ft is not None and row.score_away_ft is not None:
                score = f"{row.score_home_ft}-{row.score_away_ft}"
            elif row.score_home_ht is not None and row.score_away_ht is not None:
                score = f"{row.score_home_ht}-{row.score_away_ht} (HT)"

            fixtures.append({
                "fixture_id": row.id,
                "home_team": row.home_team,
                "away_team": row.away_team,
                "league": row.league_name,
                "date": str(row.date),
                "kickoff": str(row.kickoff_time),
                "status": row.status,
                "score": score,
            })

        return {"fixtures": fixtures, "count": len(fixtures)}

    async def _execute_function(self, name: str, args: dict) -> dict | list:
        """Route a function call to the appropriate backend service."""
        engine = self._get_engine()
        builder = self._get_builder()

        if name == "get_predictions":
            target_date = self._safe_parse_date(args.get("date", ""))
            value_only = bool(args.get("value_only", False))

            if value_only:
                preds = await engine.get_value_bets_for_date(target_date)
            else:
                preds = await engine.get_predictions_for_date(target_date)

            # Filter to upcoming (NS) fixtures unless include_all_statuses is set
            include_all = bool(args.get("include_all_statuses", False))
            if not include_all:
                upcoming_ids = await get_upcoming_fixture_ids(target_date, self.session_factory)
                preds = [p for p in preds if p["fixture_id"] in upcoming_ids]

            # Apply optional filters
            market_filter = args.get("market")
            if market_filter and market_filter in self._VALID_MARKETS:
                preds = [p for p in preds if p["market"] == market_filter]

            min_conf = args.get("min_confidence")
            if min_conf is not None:
                min_conf = max(0, min(100, int(min_conf)))
                preds = [p for p in preds if p["confidence_score"] >= min_conf]

            if not preds:
                return {
                    "predictions": [],
                    "count": 0,
                    "message": "No upcoming games with predictions for this date. All fixtures may have already kicked off or finished.",
                }

            return {"predictions": preds, "count": len(preds)}

        elif name == "build_ticket":
            target_date = self._safe_parse_date(args.get("date", ""))
            num_games = max(1, min(15, int(args.get("num_games", 3))))
            target_odds = args.get("target_odds")
            if target_odds is not None:
                target_odds = max(1.0, min(10000.0, float(target_odds)))
            preferred_markets = args.get("preferred_markets")
            if preferred_markets:
                preferred_markets = [m for m in preferred_markets if m in self._VALID_MARKETS]
            min_confidence = max(0, min(100, int(args.get("min_confidence", 60))))

            # Get upcoming fixture IDs for filtering
            upcoming_ids = await get_upcoming_fixture_ids(target_date, self.session_factory)

            return await builder.build_ticket(
                target_date=target_date,
                num_games=num_games,
                target_odds=target_odds,
                preferred_markets=preferred_markets,
                min_confidence=min_confidence,
                upcoming_fixture_ids=upcoming_ids,
            )

        elif name == "analyze_fixture":
            fixture_id = max(1, int(args.get("fixture_id", 0)))
            analysis = await engine.analyze_fixture(fixture_id)

            if "error" not in analysis:
                status = analysis.get("status", "")
                if status in ("FT", "AET", "PEN"):
                    analysis["status_note"] = (
                        "This fixture has finished. Predictions shown are what the model "
                        "would have recommended before kickoff — useful for review and backtesting."
                    )
                elif status in ("1H", "2H", "HT", "ET", "BT", "P"):
                    analysis["status_note"] = (
                        "This fixture is currently live. Predictions are pre-match only "
                        "and do not account for in-game events."
                    )

            return analysis

        elif name == "swap_ticket_game":
            ticket_id = str(args.get("ticket_id", ""))
            fixture_id_to_remove = max(1, int(args.get("fixture_id_to_remove", 0)))
            preference = args.get("preference", "safer")
            if preference not in self._VALID_PREFERENCES:
                preference = "safer"

            target_date = date.today()
            upcoming_ids = await get_upcoming_fixture_ids(target_date, self.session_factory)

            return await builder.swap_game(
                ticket_id=ticket_id,
                fixture_id_to_remove=fixture_id_to_remove,
                target_date=target_date,
                preference=preference,
                upcoming_fixture_ids=upcoming_ids,
            )

        elif name == "search_fixtures":
            team_query = str(args.get("team_name", "")).strip()
            if not team_query:
                return {"error": "team_name is required"}

            raw_date = args.get("date")
            if raw_date:
                center_date = self._safe_parse_date(raw_date)
            else:
                center_date = date.today()

            status_filter = str(args.get("status", "all")).lower()

            return await self._search_fixtures_by_team(
                team_query, center_date, status_filter
            )

        else:
            return {"error": "Unknown function"}

    @staticmethod
    def _make_serializable(obj) -> dict | list | str:
        """Ensure the result is JSON-serializable for Gemini."""
        if isinstance(obj, (dict, list)):
            try:
                return json.loads(json.dumps(obj, default=str))
            except (TypeError, ValueError):
                return {"data": str(obj)}
        return {"data": str(obj)}
