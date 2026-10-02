"""One fail-closed gate for every Google/Gemini call."""

from app.config import settings

GEMINI_PAUSED_REASON = "gemini_api_paused"


class GeminiPausedError(RuntimeError):
    """A deliberate pause, not a transient provider failure to retry."""


def is_gemini_enabled() -> bool:
    return settings.GEMINI_API_ENABLED is True


def require_gemini_enabled() -> None:
    if not is_gemini_enabled():
        raise GeminiPausedError("AI chat is temporarily paused.")
