"""
User usage model for AI quota/cost protection.

Tracks per-user, per-day AI usage so limits (requests, output tokens) can be
enforced without storing message contents. This is the foundation for
future plans (guest / free / pro); only aggregate counters are kept.
"""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserUsage(Base):
    """Daily aggregate AI usage for a user."""

    __tablename__ = "user_usage"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_user_usage_day"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<UserUsage(user_id={self.user_id}, date={self.usage_date}, reqs={self.request_count})>"
