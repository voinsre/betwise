from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(100))
    country_code: Mapped[str] = mapped_column(String(10))
    season: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))  # "League" or "Cup"
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_standings: Mapped[bool] = mapped_column(Boolean, default=False)
    has_statistics: Mapped[bool] = mapped_column(Boolean, default=False)
    has_odds: Mapped[bool] = mapped_column(Boolean, default=False)
    has_injuries: Mapped[bool] = mapped_column(Boolean, default=False)
    has_predictions: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    teams = relationship("Team", back_populates="league")
    fixtures = relationship("Fixture", back_populates="league")
