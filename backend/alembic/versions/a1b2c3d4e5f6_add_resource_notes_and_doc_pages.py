"""add resource notes and doc_pages table

Revision ID: a1b2c3d4e5f6
Revises: 22025c1effec
Create Date: 2026-03-25 14:50:00.000000
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "22025c1effec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add notes column to resources table
    op.add_column("resources", sa.Column("notes", sa.Text(), nullable=True))

    # Create doc_pages table
    op.create_table(
        "doc_pages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("locked_by", sa.UUID(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["user_groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_doc_pages_owner_id"), "doc_pages", ["owner_id"])
    op.create_index(op.f("ix_doc_pages_slug"), "doc_pages", ["slug"])


def downgrade() -> None:
    op.drop_index(op.f("ix_doc_pages_slug"), table_name="doc_pages")
    op.drop_index(op.f("ix_doc_pages_owner_id"), table_name="doc_pages")
    op.drop_table("doc_pages")
    op.drop_column("resources", "notes")
