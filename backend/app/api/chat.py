from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session, get_db

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    session_id: str | None = None


@router.post("/")
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Send message to Gemini chat with function calling."""
    if not settings.GEMINI_API_KEY:
        return {"response": "Gemini API key not configured. Set GEMINI_API_KEY in .env"}

    try:
        from app.services.gemini_chat import GeminiChatService
    except ImportError as e:
        return {"response": f"Chat service unavailable: {e}"}

    service = GeminiChatService(async_session)
    response_text, updated_history, structured_data = await service.chat(
        user_message=request.message,
        history=request.history,
    )

    result = {
        "response": response_text,
        "history": updated_history,
    }
    if structured_data is not None:
        result["structured_data"] = structured_data
    return result
