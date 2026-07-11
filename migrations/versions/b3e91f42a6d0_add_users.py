"""add users table (auth + stripe fields)

Revision ID: b3e91f42a6d0
Revises: 7a41c90d55e2
Create Date: 2026-07-09

"""

import sqlalchemy as sa
from alembic import op

revision = "b3e91f42a6d0"
down_revision = "7a41c90d55e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_id", sa.String(length=30), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=True),
        sa.Column("avatar_url", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=100), nullable=True),
        sa.Column("subscription_status", sa.String(length=30), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_id"),
        sa.UniqueConstraint("stripe_customer_id"),
    )


def downgrade() -> None:
    op.drop_table("users")
