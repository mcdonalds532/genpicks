"""add predictions.explanation

Revision ID: e5a913c7f204
Revises: b3e91f42a6d0
Create Date: 2026-07-11

"""

import sqlalchemy as sa
from alembic import op

revision = "e5a913c7f204"
down_revision = "b3e91f42a6d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("explanation", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.drop_column("explanation")
