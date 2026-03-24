"""add_cascade_to_resource_security_groups

Revision ID: 38e231f7ff8d
Revises: ccad38e35da2
Create Date: 2026-03-12 13:57:22.647350
"""

from typing import Sequence

from alembic import op


revision: str = "38e231f7ff8d"
down_revision: str | None = "ccad38e35da2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "resource_security_groups_security_group_id_fkey", "resource_security_groups", type_="foreignkey"
    )
    op.drop_constraint("resource_security_groups_resource_id_fkey", "resource_security_groups", type_="foreignkey")
    op.create_foreign_key(
        "resource_security_groups_resource_id_fkey",
        "resource_security_groups",
        "resources",
        ["resource_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "resource_security_groups_security_group_id_fkey",
        "resource_security_groups",
        "security_groups",
        ["security_group_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "resource_security_groups_security_group_id_fkey", "resource_security_groups", type_="foreignkey"
    )
    op.drop_constraint("resource_security_groups_resource_id_fkey", "resource_security_groups", type_="foreignkey")
    op.create_foreign_key(
        "resource_security_groups_resource_id_fkey", "resource_security_groups", "resources", ["resource_id"], ["id"]
    )
    op.create_foreign_key(
        "resource_security_groups_security_group_id_fkey",
        "resource_security_groups",
        "security_groups",
        ["security_group_id"],
        ["id"],
    )
