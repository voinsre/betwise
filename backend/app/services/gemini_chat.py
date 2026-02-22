"""Gemini chat service with structured function calling — Phase 7.

Uses Google Gemini 2.5 Flash with 4 tool functions that route to
the backend prediction engine and ticket builder for real data.
"""

import json
import logging
from datetime import date

import google.generativeai as genai
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
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
- If anything is ambiguous, ask for clarification.
- Star ratings: ★★★ = confidence 80+, ★★☆ = 65-79, ★☆☆ = 50-64
- When showing predictions, format them as a clear table or list with match, market, selection, odds, edge, and confidence.
- All predictions are automatically filtered to only show upcoming (not started) fixtures. If no games are available, suggest the user check back later or ask about tomorrow's fixtures.
- Today's date is {today}.
""".strip()


def _build_tools() -> list:
    """Build the 4 function declarations for Gemini tool calling."""
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
                logger.error("Function %s failed: %s", fn_name, e)
                result = {"error": str(e)}

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

    async def _execute_function(self, name: str, args: dict) -> dict | list:
        """Route a function call to the appropriate backend service."""
        engine = self._get_engine()
        builder = self._get_builder()

        if name == "get_predictions":
            target_date = date.fromisoformat(args["date"])
            value_only = args.get("value_only", False)

            if value_only:
                preds = await engine.get_value_bets_for_date(target_date)
            else:
                preds = await engine.get_predictions_for_date(target_date)

            # Filter to upcoming (NS) fixtures only — live check via API-Football
            upcoming_ids = await get_upcoming_fixture_ids(target_date, self.session_factory)
            preds = [p for p in preds if p["fixture_id"] in upcoming_ids]

            # Apply optional filters
            market_filter = args.get("market")
            if market_filter:
                preds = [p for p in preds if p["market"] == market_filter]

            min_conf = args.get("min_confidence")
            if min_conf is not None:
                preds = [p for p in preds if p["confidence_score"] >= int(min_conf)]

            if not preds:
                return {
                    "predictions": [],
                    "count": 0,
                    "message": "No upcoming games with predictions for this date. All fixtures may have already kicked off or finished.",
                }

            return {"predictions": preds, "count": len(preds)}

        elif name == "build_ticket":
            target_date = date.fromisoformat(args["date"])
            num_games = int(args["num_games"])
            target_odds = args.get("target_odds")
            if target_odds is not None:
                target_odds = float(target_odds)
            preferred_markets = args.get("preferred_markets")
            min_confidence = int(args.get("min_confidence", 60))

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
            fixture_id = int(args["fixture_id"])
            analysis = await engine.analyze_fixture(fixture_id)

            # Warn if fixture is no longer upcoming
            upcoming_ids = await get_upcoming_fixture_ids(date.today(), self.session_factory)
            if fixture_id not in upcoming_ids and "error" not in analysis:
                analysis["warning"] = (
                    "This fixture has already started or finished. "
                    "Predictions are for reference only — not bettable."
                )

            return analysis

        elif name == "swap_ticket_game":
            ticket_id = str(args["ticket_id"])
            fixture_id_to_remove = int(args["fixture_id_to_remove"])
            preference = args.get("preference", "safer")

            target_date = date.today()
            upcoming_ids = await get_upcoming_fixture_ids(target_date, self.session_factory)

            return await builder.swap_game(
                ticket_id=ticket_id,
                fixture_id_to_remove=fixture_id_to_remove,
                target_date=target_date,
                preference=preference,
                upcoming_fixture_ids=upcoming_ids,
            )

        else:
            return {"error": f"Unknown function: {name}"}

    @staticmethod
    def _make_serializable(obj) -> dict | list | str:
        """Ensure the result is JSON-serializable for Gemini."""
        if isinstance(obj, (dict, list)):
            try:
                return json.loads(json.dumps(obj, default=str))
            except (TypeError, ValueError):
                return {"data": str(obj)}
        return {"data": str(obj)}
