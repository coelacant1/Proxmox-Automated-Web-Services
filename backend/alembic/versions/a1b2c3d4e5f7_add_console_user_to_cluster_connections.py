"""add console_user and console_password_enc to cluster_connections

Revision ID: a1b2c3d4e5f7
Revises: b2c3d4e5f6a7
Create Date: 2026-06-15 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f7"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cluster_connections", sa.Column("console_user", sa.String(255), nullable=True))
    op.add_column("cluster_connections", sa.Column("console_password_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cluster_connections", "console_password_enc")
    op.drop_column("cluster_connections", "console_user")
