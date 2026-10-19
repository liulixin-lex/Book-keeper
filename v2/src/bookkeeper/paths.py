"""Filesystem locations inside the source tree / image."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent.parent
ALEMBIC_INI = PROJECT_DIR / "alembic.ini"
