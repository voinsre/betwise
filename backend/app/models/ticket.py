import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    games: Mapped[list] = mapped_column(JSONB, default=list)
    num_games: Mapped[int] = mapped_column(Integer)
    combined_odds: Mapped[float] = mapped_column(Float)
    combined_probability: Mapped[float] = mapped_column(Float)
    kelly_stake: Mapped[float] = mapped_column(Float)
    target_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    profit_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
