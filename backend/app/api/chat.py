import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session, get_db

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    history: list[dict] = Field(default_factory=list, max_length=50)
    session_id: str | None = None


@router.post("/")
@limiter.limit("10/minute")
async def chat(
    request_body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send message to Gemini chat with function calling."""
    if not settings.GEMINI_API_KEY:
        return {"response": "Chat service is not configured."}

    try:
        from app.services.gemini_chat import GeminiChatService
    except ImportError:
        logger.error("GeminiChatService import failed", exc_info=True)
        return {"response": "Chat service unavailable."}

    service = GeminiChatService(async_session)
    response_text, updated_history, structured_data = await service.chat(
        user_message=request_body.message,
        history=request_body.history,
    )

    result = {
        "response": response_text,
        "history": updated_history,
    }
    if structured_data is not None:
        result["structured_data"] = structured_data
    return result
