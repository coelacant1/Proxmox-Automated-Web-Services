"""Add drift_events table.

Revision ID: b1c2d3e4f5a6
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "b1c2d3e4f5a6"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drift_events",
        sa.Column("id", PG_UUID(as_uuid=False), primary_key=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "resource_id", PG_UUID(as_uuid=False), sa.ForeignKey("resources.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("proxmox_vmid", sa.Integer, nullable=True),
        sa.Column("proxmox_node", sa.String(100), nullable=True),
        sa.Column("drift_type", sa.String(50), nullable=False),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("acknowledged", sa.Boolean, default=False, nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acknowledged_by", PG_UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("ix_drift_events_detected_at", "drift_events", ["detected_at"])
    op.create_index("ix_drift_events_resource_id", "drift_events", ["resource_id"])
    op.create_index("ix_drift_events_drift_type", "drift_events", ["drift_type"])
    op.create_index("ix_drift_events_acknowledged", "drift_events", ["acknowledged"])


def downgrade() -> None:
    op.drop_index("ix_drift_events_acknowledged", "drift_events")
    op.drop_index("ix_drift_events_drift_type", "drift_events")
    op.drop_index("ix_drift_events_resource_id", "drift_events")
    op.drop_index("ix_drift_events_detected_at", "drift_events")
    op.drop_table("drift_events")
