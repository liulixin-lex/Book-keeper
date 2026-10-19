"""Declarative base with constraint naming conventions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(TZ, onupdate=func.now())


class Versioned:
    version: Mapped[int] = mapped_column(server_default="1", default=1, nullable=False)
