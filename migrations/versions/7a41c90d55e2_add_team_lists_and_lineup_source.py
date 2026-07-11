"""add team_list_entries and predictions.lineup_source

Revision ID: 7a41c90d55e2
Revises: c8de4107249e
Create Date: 2026-07-07

"""

import sqlalchemy as sa
from alembic import op

revision = "7a41c90d55e2"
down_revision = "c8de4107249e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_list_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("player_name", sa.String(length=150), nullable=False),
        sa.Column("position", sa.String(length=30), nullable=True),
        sa.Column("jersey_number", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("team_list_entries", schema=None) as batch_op:
        batch_op.create_index("ix_team_list_entries_match", ["match_id"], unique=False)

    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lineup_source", sa.String(length=20), nullable=True))

    # every try-market prediction generated before this migration used a
    # lineup projected from the team's last played match
    op.execute(
        "UPDATE predictions SET lineup_source = 'projected' "
        "WHERE market IN ('anytime_try', 'first_try')"
    )


def downgrade() -> None:
    with op.batch_alter_table("predictions", schema=None) as batch_op:
        batch_op.drop_column("lineup_source")

    with op.batch_alter_table("team_list_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_team_list_entries_match")

    op.drop_table("team_list_entries")
