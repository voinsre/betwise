from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    league_id: Mapped[int] = mapped_column(Integer, ForeignKey("leagues.id"))
    country: Mapped[str] = mapped_column(String(100))
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    founded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    venue_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    league = relationship("League", back_populates="teams")
