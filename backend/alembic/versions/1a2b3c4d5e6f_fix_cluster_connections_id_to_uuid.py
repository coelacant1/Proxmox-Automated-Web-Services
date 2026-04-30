"""Fix cluster_connections.id column type from CHAR to UUID.

Revision ID: 1a2b3c4d5e6f
Revises: f6a7b8c9d0e1, a1b2c3d4e5f7
Create Date: 2026-04-21

"""

from alembic import op
from sqlalchemy import text

revision: str = "1a2b3c4d5e6f"
down_revision = ("f6a7b8c9d0e1", "a1b2c3d4e5f7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'cluster_connections' AND column_name = 'id'"
        )
    )
    col_type = result.scalar()
    if col_type and col_type.lower() != "uuid":
        op.execute(text("ALTER TABLE cluster_connections ALTER COLUMN id TYPE uuid USING id::uuid"))


def downgrade() -> None:
    op.execute(text("ALTER TABLE cluster_connections ALTER COLUMN id TYPE character(36) USING id::text"))
