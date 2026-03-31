"""Add cluster_id to SecurityGroup, IPReservation, HealthCheck.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: str = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- security_groups ---
    op.add_column(
        "security_groups",
        sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"),
    )
    op.create_index("ix_security_groups_cluster_id", "security_groups", ["cluster_id"])

    # --- ip_reservations ---
    op.add_column(
        "ip_reservations",
        sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"),
    )
    op.create_index("ix_ip_reservations_cluster_id", "ip_reservations", ["cluster_id"])

    # --- health_checks ---
    op.add_column(
        "health_checks",
        sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"),
    )
    op.create_index("ix_health_checks_cluster_id", "health_checks", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_health_checks_cluster_id", "health_checks")
    op.drop_column("health_checks", "cluster_id")

    op.drop_index("ix_ip_reservations_cluster_id", "ip_reservations")
    op.drop_column("ip_reservations", "cluster_id")

    op.drop_index("ix_security_groups_cluster_id", "security_groups")
    op.drop_column("security_groups", "cluster_id")
