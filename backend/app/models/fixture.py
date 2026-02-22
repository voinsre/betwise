from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Fixture(Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    date: Mapped[date] = mapped_column(Date)
    kickoff_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    league_id: Mapped[int] = mapped_column(Integer, ForeignKey("leagues.id"))
    season: Mapped[int] = mapped_column(Integer)
    round: Mapped[str | None] = mapped_column(String(50), nullable=True)
    venue: Mapped[str | None] = mapped_column(String(200), nullable=True)
    referee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="NS")
    score_home_ht: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_away_ht: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_home_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_away_ft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_home_et: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_away_et: Mapped[int | None] = mapped_column(Integer, nullable=True)

    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
    league = relationship("League", back_populates="fixtures")
    statistics = relationship("FixtureStatistics", back_populates="fixture")
    predictions = relationship("Prediction", back_populates="fixture")
    odds = relationship("Odds", back_populates="fixture")
    injuries = relationship("Injury", back_populates="fixture")
