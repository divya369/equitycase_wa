"""Import every table model here so Alembic autogenerate sees it.

Tables are added in P1 (modules/*/models.py).
"""

from sqlmodel import SQLModel

__all__ = ["SQLModel"]
