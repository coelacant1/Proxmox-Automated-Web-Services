"""Add cluster_id to VPC, Volume, Backup, BackupPlan, HAGroup.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: str = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- volumes ---
    op.add_column("volumes", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    op.create_index("ix_volumes_cluster_id", "volumes", ["cluster_id"])

    # --- vpcs ---
    op.add_column("vpcs", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    op.create_index("ix_vpcs_cluster_id", "vpcs", ["cluster_id"])
    # Drop old unique on vxlan_tag if it exists, add composite (cluster_id, vxlan_tag)
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = 'uq_vpcs_vxlan_tag' AND table_name = 'vpcs'"
        )
    ).fetchone()
    if row:
        op.drop_constraint("uq_vpcs_vxlan_tag", "vpcs", type_="unique")
    op.create_unique_constraint("uq_vpc_cluster_vxlan", "vpcs", ["cluster_id", "vxlan_tag"])

    # --- backups ---
    op.add_column("backups", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    op.create_index("ix_backups_cluster_id", "backups", ["cluster_id"])

    # --- backup_plans ---
    op.add_column("backup_plans", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    op.create_index("ix_backup_plans_cluster_id", "backup_plans", ["cluster_id"])

    # --- ha_groups ---
    op.add_column("ha_groups", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    op.create_index("ix_ha_groups_cluster_id", "ha_groups", ["cluster_id"])
    # Drop old unique on pve_group_name if it exists, add composite
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = 'uq_ha_groups_pve_group_name' AND table_name = 'ha_groups'"
        )
    ).fetchone()
    if row:
        op.drop_constraint("uq_ha_groups_pve_group_name", "ha_groups", type_="unique")
    op.create_unique_constraint("uq_ha_cluster_pvename", "ha_groups", ["cluster_id", "pve_group_name"])


def downgrade() -> None:
    # --- ha_groups ---
    op.drop_constraint("uq_ha_cluster_pvename", "ha_groups", type_="unique")
    op.create_unique_constraint("uq_ha_groups_pve_group_name", "ha_groups", ["pve_group_name"])
    op.drop_index("ix_ha_groups_cluster_id", "ha_groups")
    op.drop_column("ha_groups", "cluster_id")

    # --- backup_plans ---
    op.drop_index("ix_backup_plans_cluster_id", "backup_plans")
    op.drop_column("backup_plans", "cluster_id")

    # --- backups ---
    op.drop_index("ix_backups_cluster_id", "backups")
    op.drop_column("backups", "cluster_id")

    # --- vpcs ---
    op.drop_constraint("uq_vpc_cluster_vxlan", "vpcs", type_="unique")
    op.create_unique_constraint("uq_vpcs_vxlan_tag", "vpcs", ["vxlan_tag"])
    op.drop_index("ix_vpcs_cluster_id", "vpcs")
    op.drop_column("vpcs", "cluster_id")

    # --- volumes ---
    op.drop_index("ix_volumes_cluster_id", "volumes")
    op.drop_column("volumes", "cluster_id")
