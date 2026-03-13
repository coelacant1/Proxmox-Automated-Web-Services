"""add network_mode to vpcs and max_subnet_prefix to user_tiers

Revision ID: 3cb77e634c99
Revises: ef2bd0f7b7ce
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3cb77e634c99"
down_revision: Union[str, None] = "38e231f7ff8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vpcs",
        sa.Column("network_mode", sa.String(20), nullable=False, server_default="private"),
    )
    op.add_column(
        "user_tiers",
        sa.Column("max_subnet_prefix", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_tiers", "max_subnet_prefix")
    op.drop_column("vpcs", "network_mode")
