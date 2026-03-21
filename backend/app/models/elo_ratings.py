import datetime as dt

from sqlalchemy import Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EloRating(Base):
    """Club Elo ratings sourced from ClubElo CSV."""
    __tablename__ = "elo_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_name: Mapped[str] = mapped_column(String(100), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    elo: Mapped[float] = mapped_column(Float)
    country: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        UniqueConstraint("team_name", "date", name="uq_elo_team_date"),
    )
