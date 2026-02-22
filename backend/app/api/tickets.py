import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models.fixture import Fixture
from app.models.ticket import Ticket
from app.services.prediction_engine import PredictionEngine
from app.services.ticket_builder import TicketBuilder

router = APIRouter()


class TicketBuildRequest(BaseModel):
    date: str
    num_games: int
    target_odds: float | None = None
    preferred_markets: list[str] | None = None
    min_confidence: int = 60
    bankroll: float = 1000.0


class TicketSwapRequest(BaseModel):
    fixture_id_to_remove: int
    preference: str = "safer"


def _get_builder() -> TicketBuilder:
    engine = PredictionEngine(async_session)
    engine.load_models()
    return TicketBuilder(async_session, engine)


@router.post("/build")
async def build_ticket(request: TicketBuildRequest, db: AsyncSession = Depends(get_db)):
    """Build an optimized ticket."""
    try:
        target = date.fromisoformat(request.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    builder = _get_builder()
    result = await builder.build_ticket(
        target_date=target,
        num_games=request.num_games,
        target_odds=request.target_odds,
        preferred_markets=request.preferred_markets,
        min_confidence=request.min_confidence,
        bankroll=request.bankroll,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"ticket": result}


@router.post("/{ticket_id}/swap")
async def swap_game(
    ticket_id: str,
    request: TicketSwapRequest,
    db: AsyncSession = Depends(get_db),
):
    """Swap a game in a ticket."""
    builder = _get_builder()

    # Determine the date from the ticket
    async with async_session() as session:
        try:
            tid = uuid.UUID(ticket_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ticket ID")
        ticket = await session.get(Ticket, tid)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        if ticket.games:
            fix = await session.get(Fixture, ticket.games[0]["fixture_id"])
            target = fix.date if fix else date.today()
        else:
            target = date.today()

    result = await builder.swap_game(
        ticket_id=ticket_id,
        fixture_id_to_remove=request.fixture_id_to_remove,
        target_date=target,
        preference=request.preference,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"ticket": result}


@router.get("/")
async def list_tickets(db: AsyncSession = Depends(get_db)):
    """List all tickets, most recent first."""
    result = await db.execute(
        select(Ticket).order_by(Ticket.created_at.desc()).limit(50)
    )
    tickets = result.scalars().all()

    items = []
    for t in tickets:
        items.append({
            "id": str(t.id),
            "num_games": t.num_games,
            "combined_odds": t.combined_odds,
            "combined_probability": t.combined_probability,
            "kelly_stake": t.kelly_stake,
            "status": t.status,
            "profit_loss": t.profit_loss,
            "created_at": str(t.created_at) if t.created_at else None,
        })

    return {"count": len(items), "tickets": items}


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: str, db: AsyncSession = Depends(get_db)):
    """Get ticket details."""
    try:
        tid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ticket ID")

    ticket = await db.get(Ticket, tid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {
        "ticket": {
            "id": str(ticket.id),
            "games": ticket.games,
            "num_games": ticket.num_games,
            "combined_odds": ticket.combined_odds,
            "combined_probability": ticket.combined_probability,
            "kelly_stake": ticket.kelly_stake,
            "target_odds": ticket.target_odds,
            "status": ticket.status,
            "profit_loss": ticket.profit_loss,
            "settled_at": str(ticket.settled_at) if ticket.settled_at else None,
            "created_at": str(ticket.created_at) if ticket.created_at else None,
        }
    }
