from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Odds(Base):
    __tablename__ = "odds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(Integer, ForeignKey("fixtures.id"))
    bookmaker_id: Mapped[int] = mapped_column(Integer)
    bookmaker_name: Mapped[str] = mapped_column(String(100))
    market: Mapped[str] = mapped_column(String(20))  # "1x2", "ou25", "btts", "dc", "htft", "combo"
    label: Mapped[str] = mapped_column(String(50))
    value: Mapped[float] = mapped_column(Float)
    implied_probability: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    fixture = relationship("Fixture", back_populates="odds")

    __table_args__ = (
        Index("ix_odds_fixture_market", "fixture_id", "market"),
    )
