from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Injury(Base):
    __tablename__ = "injuries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(Integer, ForeignKey("fixtures.id"))
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(Integer)
    player_name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(50))  # "Missing Fixture", "Questionable", "Injured", "Suspended"
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    fixture = relationship("Fixture", back_populates="injuries")
    team = relationship("Team")
