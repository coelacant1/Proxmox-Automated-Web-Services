"""add last_login_at to users

Revision ID: a3e7f1c24d90
Revises: 0b968bc0e811
Create Date: 2026-03-10 17:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3e7f1c24d90"
down_revision: Union[str, None] = "0b968bc0e811"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
