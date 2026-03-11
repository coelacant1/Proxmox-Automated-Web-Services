"""add lifecycle overrides to user_tiers

Revision ID: d5f2a8b91c03
Revises: a3e7f1c24d90
Create Date: 2026-03-10 17:50:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5f2a8b91c03"
down_revision: Union[str, None] = "a3e7f1c24d90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_tiers", sa.Column("idle_shutdown_days", sa.Integer(), nullable=True))
    op.add_column("user_tiers", sa.Column("idle_destroy_days", sa.Integer(), nullable=True))
    op.add_column("user_tiers", sa.Column("account_inactive_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_tiers", "account_inactive_days")
    op.drop_column("user_tiers", "idle_destroy_days")
    op.drop_column("user_tiers", "idle_shutdown_days")
