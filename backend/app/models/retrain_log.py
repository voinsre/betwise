from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RetrainLog(Base):
    __tablename__ = "retrain_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # running, success, failed, skipped
    market: Mapped[str] = mapped_column(String(20))  # 1x2, ou25, btts, htft
    train_range: Mapped[str | None] = mapped_column(String(100), nullable=True)
    val_range: Mapped[str | None] = mapped_column(String(100), nullable=True)
    train_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    val_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_params: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), default="celery_beat")
