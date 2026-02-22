from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TeamLast20(Base):
    __tablename__ = "team_last20"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    fixture_id: Mapped[int] = mapped_column(Integer, ForeignKey("fixtures.id"))
    date: Mapped[date] = mapped_column(Date)
    opponent_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    venue: Mapped[str] = mapped_column(String(1))  # "H" or "A"
    goals_for: Mapped[int] = mapped_column(Integer)
    goals_against: Mapped[int] = mapped_column(Integer)
    xg_for: Mapped[float | None] = mapped_column(Float, nullable=True)
    xg_against: Mapped[float | None] = mapped_column(Float, nullable=True)
    shots_on_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shots_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    possession: Mapped[float | None] = mapped_column(Float, nullable=True)
    corners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(1))  # "W", "D", "L"
    form_weight: Mapped[float] = mapped_column(Float)
    league_id: Mapped[int] = mapped_column(Integer, ForeignKey("leagues.id"))
    season: Mapped[int] = mapped_column(Integer)

    team = relationship("Team", foreign_keys=[team_id])
    opponent = relationship("Team", foreign_keys=[opponent_id])
    fixture = relationship("Fixture")

    __table_args__ = (
        UniqueConstraint("team_id", "fixture_id", name="uq_team_fixture"),
        Index("ix_team_last20_team_date", "team_id", "date"),
    )
