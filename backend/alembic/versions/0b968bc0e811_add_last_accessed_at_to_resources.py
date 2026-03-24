"""add last_accessed_at to resources

Revision ID: 0b968bc0e811
Revises: b6c31f607d6e
Create Date: 2026-03-10 17:20:00.000000
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0b968bc0e811"
down_revision: str | None = "b6c31f607d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("resources", "last_accessed_at")
