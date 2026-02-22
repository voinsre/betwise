from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelAccuracy(Base):
    __tablename__ = "model_accuracy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    market: Mapped[str] = mapped_column(String(20))
    league_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("leagues.id"), nullable=True)
    total_predictions: Mapped[int] = mapped_column(Integer)
    correct_predictions: Mapped[int] = mapped_column(Integer)
    accuracy_pct: Mapped[float] = mapped_column(Float)
    avg_edge: Mapped[float] = mapped_column(Float)
    avg_confidence: Mapped[int] = mapped_column(Integer)
    total_staked: Mapped[float] = mapped_column(Float)
    total_returned: Mapped[float] = mapped_column(Float)
    profit_loss: Mapped[float] = mapped_column(Float)
    roi_pct: Mapped[float] = mapped_column(Float)
