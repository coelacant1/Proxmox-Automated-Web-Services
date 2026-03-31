"""add_cluster_id_to_resources_templates_vmidpool

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-16 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: str = "b2c3d4e5f6a7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- resources table ---
    op.add_column("resources", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    # Drop old unique constraint on proxmox_vmid if it exists
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = 'resources_proxmox_vmid_key' AND table_name = 'resources'"
        )
    ).fetchone()
    if row:
        op.drop_constraint("resources_proxmox_vmid_key", "resources", type_="unique")
    # Create composite unique constraint (cluster_id, proxmox_vmid)
    op.create_unique_constraint("uq_resource_cluster_vmid", "resources", ["cluster_id", "proxmox_vmid"])
    op.create_index("ix_resources_cluster_id", "resources", ["cluster_id"])

    # --- template_catalog table ---
    op.add_column("template_catalog", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = 'template_catalog_proxmox_vmid_key' AND table_name = 'template_catalog'"
        )
    ).fetchone()
    if row:
        op.drop_constraint("template_catalog_proxmox_vmid_key", "template_catalog", type_="unique")
    op.create_unique_constraint("uq_template_cluster_vmid", "template_catalog", ["cluster_id", "proxmox_vmid"])
    op.create_index("ix_template_catalog_cluster_id", "template_catalog", ["cluster_id"])

    # --- vmid_pool table ---
    op.add_column("vmid_pool", sa.Column("cluster_id", sa.String(100), nullable=False, server_default="default"))
    # VMIDPool previously had vmid as sole PK; add cluster_id to composite PK
    op.execute("ALTER TABLE vmid_pool DROP CONSTRAINT vmid_pool_pkey")
    op.create_primary_key("vmid_pool_pkey", "vmid_pool", ["vmid", "cluster_id"])
    op.create_unique_constraint("uq_vmidpool_cluster_vmid", "vmid_pool", ["cluster_id", "vmid"])


def downgrade() -> None:
    # --- vmid_pool ---
    op.drop_constraint("uq_vmidpool_cluster_vmid", "vmid_pool", type_="unique")
    op.execute("ALTER TABLE vmid_pool DROP CONSTRAINT vmid_pool_pkey")
    op.create_primary_key("vmid_pool_pkey", "vmid_pool", ["vmid"])
    op.drop_column("vmid_pool", "cluster_id")

    # --- template_catalog ---
    op.drop_index("ix_template_catalog_cluster_id", "template_catalog")
    op.drop_constraint("uq_template_cluster_vmid", "template_catalog", type_="unique")
    op.create_unique_constraint("template_catalog_proxmox_vmid_key", "template_catalog", ["proxmox_vmid"])
    op.drop_column("template_catalog", "cluster_id")

    # --- resources ---
    op.drop_index("ix_resources_cluster_id", "resources")
    op.drop_constraint("uq_resource_cluster_vmid", "resources", type_="unique")
    op.create_unique_constraint("resources_proxmox_vmid_key", "resources", ["proxmox_vmid"])
    op.drop_column("resources", "cluster_id")
