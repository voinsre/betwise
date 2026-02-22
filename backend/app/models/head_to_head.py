from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HeadToHead(Base):
    __tablename__ = "head_to_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team1_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))  # always lower ID
    team2_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))  # always higher ID
    fixture_id: Mapped[int] = mapped_column(Integer, ForeignKey("fixtures.id"))
    date: Mapped[date] = mapped_column(Date)
    home_team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    score_home: Mapped[int] = mapped_column(Integer)
    score_away: Mapped[int] = mapped_column(Integer)
    winner: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "home", "away", "draw"
    total_goals: Mapped[int] = mapped_column(Integer)
    xg_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    xg_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    league_id: Mapped[int] = mapped_column(Integer, ForeignKey("leagues.id"))

    team1 = relationship("Team", foreign_keys=[team1_id])
    team2 = relationship("Team", foreign_keys=[team2_id])
    fixture = relationship("Fixture")
