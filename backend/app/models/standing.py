from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Standing(Base):
    __tablename__ = "standings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(Integer, ForeignKey("leagues.id"))
    season: Mapped[int] = mapped_column(Integer)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    rank: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    played: Mapped[int] = mapped_column(Integer)
    won: Mapped[int] = mapped_column(Integer)
    drawn: Mapped[int] = mapped_column(Integer)
    lost: Mapped[int] = mapped_column(Integer)
    goals_for: Mapped[int] = mapped_column(Integer)
    goals_against: Mapped[int] = mapped_column(Integer)
    goal_diff: Mapped[int] = mapped_column(Integer)
    form: Mapped[str | None] = mapped_column(String(10), nullable=True)
    home_played: Mapped[int] = mapped_column(Integer, default=0)
    home_won: Mapped[int] = mapped_column(Integer, default=0)
    home_drawn: Mapped[int] = mapped_column(Integer, default=0)
    home_lost: Mapped[int] = mapped_column(Integer, default=0)
    home_gf: Mapped[int] = mapped_column(Integer, default=0)
    home_ga: Mapped[int] = mapped_column(Integer, default=0)
    away_played: Mapped[int] = mapped_column(Integer, default=0)
    away_won: Mapped[int] = mapped_column(Integer, default=0)
    away_drawn: Mapped[int] = mapped_column(Integer, default=0)
    away_lost: Mapped[int] = mapped_column(Integer, default=0)
    away_gf: Mapped[int] = mapped_column(Integer, default=0)
    away_ga: Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    league = relationship("League")
    team = relationship("Team")
