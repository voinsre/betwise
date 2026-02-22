from sqlalchemy import Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FixtureStatistics(Base):
    __tablename__ = "fixture_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(Integer, ForeignKey("fixtures.id"))
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    shots_on_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shots_off_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_shots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blocked_shots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shots_insidebox: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shots_outsidebox: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fouls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corner_kicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offsides: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ball_possession: Mapped[float | None] = mapped_column(Float, nullable=True)
    yellow_cards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    red_cards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goalkeeper_saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_passes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passes_accurate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passes_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_goals: Mapped[float | None] = mapped_column(Float, nullable=True)

    fixture = relationship("Fixture", back_populates="statistics")
    team = relationship("Team")
