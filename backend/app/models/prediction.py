from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(Integer, ForeignKey("fixtures.id"))
    market: Mapped[str] = mapped_column(String(20))
    selection: Mapped[str] = mapped_column(String(50))
    poisson_probability: Mapped[float] = mapped_column(Float)
    ml_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    blended_probability: Mapped[float] = mapped_column(Float)
    best_odd: Mapped[float] = mapped_column(Float)
    best_bookmaker: Mapped[str] = mapped_column(String(100))
    implied_probability: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    expected_value: Mapped[float] = mapped_column(Float)
    confidence_score: Mapped[int] = mapped_column(Integer)
    is_value_bet: Mapped[bool] = mapped_column(Boolean, default=False)

    fixture = relationship("Fixture", back_populates="predictions")

    __table_args__ = (
        UniqueConstraint("fixture_id", "market", "selection", name="uq_fixture_market_selection"),
    )
