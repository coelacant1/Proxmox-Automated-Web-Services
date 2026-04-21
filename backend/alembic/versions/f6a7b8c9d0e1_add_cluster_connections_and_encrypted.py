"""Add ClusterConnection table and is_encrypted to SystemSetting.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9d0e1"
down_revision: str = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- cluster_connections table ---
    op.create_table(
        "cluster_connections",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("conn_type", sa.String(20), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer, nullable=False, server_default="8006"),
        sa.Column("token_id", sa.String(255), nullable=True),
        sa.Column("token_secret_enc", sa.Text, nullable=True),
        sa.Column("password_enc", sa.Text, nullable=True),
        sa.Column("fingerprint", sa.String(255), nullable=True),
        sa.Column("verify_ssl", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("extra_config", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_cluster_connections_conn_type", "cluster_connections", ["conn_type"])

    # --- system_settings: add is_encrypted column ---
    op.add_column(
        "system_settings",
        sa.Column("is_encrypted", sa.Boolean, nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "is_encrypted")
    op.drop_index("ix_cluster_connections_conn_type", "cluster_connections")
    op.drop_table("cluster_connections")
