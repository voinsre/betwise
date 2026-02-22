"""Test script for Phase 7 — Gemini Chat Integration.

Sends three test messages to the GeminiChatService and prints responses.

Run from the backend/ directory:
    python scripts/test_chat.py
"""

import asyncio
import os
import sys
import time

# Setup path and env
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise"
)

import logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("app.services.gemini_chat").setLevel(logging.INFO)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.gemini_chat import GeminiChatService


async def main():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("\n" + "=" * 70)
    print("  BETWISE GEMINI CHAT TEST")
    print("=" * 70)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        print("\n  ERROR: GEMINI_API_KEY not set in .env")
        await engine.dispose()
        return

    print(f"  Gemini API key: {gemini_key[:8]}...{gemini_key[-4:]}")

    service = GeminiChatService(session_factory)
    history = []

    # Test messages
    messages = [
        "What are today's best value bets?",
        "Build me a 2-game ticket around 3.0 odds",
        "Tell me more about the Crystal Palace vs Wolves match",
    ]

    for i, msg in enumerate(messages, 1):
        print(f"\n{'─' * 70}")
        print(f"  USER [{i}/{len(messages)}]: {msg}")
        print(f"{'─' * 70}")

        t0 = time.time()
        try:
            response, history = await service.chat(msg, history)
            elapsed = time.time() - t0

            print(f"\n  BETWISE AI ({elapsed:.1f}s):")
            # Indent the response for readability
            for line in response.split("\n"):
                print(f"  {line}")
        except Exception as e:
            print(f"\n  ERROR: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'─' * 70}")
    print(f"  Conversation history: {len(history)} messages")
    print("=" * 70 + "\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
