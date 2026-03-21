from sqlalchemy import Integer, String
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base


class TeamSourceMapping(Base):
    """Maps API-Football team IDs to OddsPapi participant IDs."""
    __tablename__ = "team_source_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_football_team_id: Mapped[int] = mapped_column(Integer, index=True)
    canonical_name: Mapped[str] = mapped_column(String(100))
    oddspapi_participant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oddspapi_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    clubelo_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
