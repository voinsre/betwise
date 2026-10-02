"""Offline regression tests. No installed app dependencies, env files or network needed.

Run: python -m unittest discover -s backend/tests -p test_gemini_pause.py
"""
import ast
import asyncio
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parents[1]


def module(name, **values):
    result = types.ModuleType(name)
    result.__dict__.update(values)
    return result


class GeminiPauseTests(unittest.TestCase):
    def setUp(self):
        self.settings = types.SimpleNamespace(GEMINI_API_ENABLED=False, GEMINI_API_KEY="offline-not-a-key")
        self.genai = MagicMock()
        self.engine = MagicMock(side_effect=AssertionError("Database engine must not start"))
        class BaseModel:
            pass
        class Router:
            def post(self, *_args, **_kwargs):
                return lambda fn: fn
        class Limiter:
            def __init__(self, **_kwargs):
                pass
            def limit(self, *_args, **_kwargs):
                return lambda fn: fn
        self.modules = {
            "app": module("app", __path__=[]),
            "app.services": module("app.services", __path__=[]),
            "app.config": module("app.config", settings=self.settings),
            "app.database": module("app.database", async_session=object(), get_db=lambda: None),
            "google": module("google", generativeai=self.genai),
            "google.generativeai": self.genai,
            "sqlalchemy": module("sqlalchemy", or_=MagicMock(), select=MagicMock()),
            "sqlalchemy.ext": module("sqlalchemy.ext", __path__=[]),
            "sqlalchemy.ext.asyncio": module("sqlalchemy.ext.asyncio", AsyncSession=object,
                                             async_sessionmaker=MagicMock(), create_async_engine=self.engine),
            "sqlalchemy.orm": module("sqlalchemy.orm", aliased=MagicMock()),
            "app.models.fixture": module("app.models.fixture", Fixture=object),
            "app.models.league": module("app.models.league", League=object),
            "app.models.team": module("app.models.team", Team=object),
            "app.services.live_fixtures": module("app.services.live_fixtures", get_upcoming_fixture_ids=MagicMock()),
            "app.services.prediction_engine": module("app.services.prediction_engine", PredictionEngine=MagicMock()),
            "app.services.ticket_builder": module("app.services.ticket_builder", TicketBuilder=MagicMock()),
            "fastapi": module("fastapi", APIRouter=Router, Depends=lambda fn: None, Request=object),
            "pydantic": module("pydantic", BaseModel=BaseModel, Field=lambda *_args, **_kwargs: None),
            "slowapi": module("slowapi", Limiter=Limiter),
            "slowapi.util": module("slowapi.util", get_remote_address=lambda _: "offline"),
            "dotenv": module("dotenv", load_dotenv=lambda *_args: None),
        }
        self.patcher = patch.dict(sys.modules, self.modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.policy = self.load("app.services.gemini_policy", "app/services/gemini_policy.py")
        self.service = self.load("app.services.gemini_chat", "app/services/gemini_chat.py")

    def load(self, name, relative):
        spec = importlib.util.spec_from_file_location(name, BACKEND / relative)
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded
        spec.loader.exec_module(loaded)
        return loaded

    def test_configuration_defaults_to_paused(self):
        tree = ast.parse((BACKEND / "app/config.py").read_text(encoding="utf-8"))
        settings_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
        field = next(n for n in settings_class.body if isinstance(n, ast.AnnAssign) and n.target.id == "GEMINI_API_ENABLED")
        self.assertIs(ast.literal_eval(field.value), False)

    def test_key_presence_does_not_enable_gemini(self):
        self.assertFalse(self.policy.is_gemini_enabled())
        with self.assertRaises(self.policy.GeminiPausedError):
            self.service.GeminiChatService(object())
        self.genai.configure.assert_not_called()
        self.genai.GenerativeModel.assert_not_called()

    def test_route_returns_paused_response_and_preserves_history(self):
        route = self.load("offline_chat_route", "app/api/chat.py")
        history = [{"role": "user", "content": "previous"}]
        result = asyncio.run(route.chat(types.SimpleNamespace(message="hello", history=history), object()))
        self.assertTrue(result["paused"])
        self.assertEqual(result["reason"], "gemini_api_paused")
        self.assertEqual(result["history"], history)
        self.genai.configure.assert_not_called()
        self.genai.GenerativeModel.assert_not_called()

    def test_existing_service_cannot_start_chat_after_pause(self):
        instance = self.service.GeminiChatService.__new__(self.service.GeminiChatService)
        instance.model = MagicMock()
        with self.assertRaises(self.policy.GeminiPausedError):
            asyncio.run(instance.chat("hello", []))
        instance.model.start_chat.assert_not_called()

    def test_direct_function_loop_cannot_send_while_paused(self):
        instance = self.service.GeminiChatService.__new__(self.service.GeminiChatService)
        session = MagicMock()
        with self.assertRaises(self.policy.GeminiPausedError):
            asyncio.run(instance._send_with_function_loop(session, "hello"))
        session.send_message.assert_not_called()

    def test_pause_between_function_rounds_stops_next_provider_send(self):
        self.settings.GEMINI_API_ENABLED = True
        instance = self.service.GeminiChatService.__new__(self.service.GeminiChatService)
        instance._extract_function_call = MagicMock(return_value=("search_fixtures", {}))
        def pause_after_tool(*_args):
            self.settings.GEMINI_API_ENABLED = False
            return {}
        instance._execute_function = AsyncMock(side_effect=pause_after_tool)
        instance._make_serializable = lambda value: value
        session = MagicMock()
        with self.assertRaises(self.policy.GeminiPausedError):
            asyncio.run(instance._send_with_function_loop(session, "hello"))
        self.assertEqual(session.send_message.call_count, 1)

    def test_standalone_script_skips_before_database_or_provider(self):
        with patch.object(sys, "path", list(sys.path)):
            script = self.load("offline_test_chat_script", "scripts/test_chat.py")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            asyncio.run(script.main())
        self.assertIn("SKIPPED", output.getvalue())
        self.engine.assert_not_called()
        self.genai.configure.assert_not_called()

    def test_explicit_enablement_reaches_fake_provider(self):
        self.settings.GEMINI_API_ENABLED = True
        instance = self.service.GeminiChatService(object())
        instance._extract_function_call = MagicMock(return_value=None)
        instance._extract_text = MagicMock(return_value="offline reply")
        session = MagicMock()
        result = asyncio.run(instance._send_with_function_loop(session, "hello"))
        self.assertEqual(result, ("offline reply", None))
        self.genai.configure.assert_called_once()
        session.send_message.assert_called_once_with("hello")


if __name__ == "__main__":
    unittest.main()
