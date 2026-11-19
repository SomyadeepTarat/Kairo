"""Persist benchmark configuration and measured case outcomes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("configuration", JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("results", JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("evaluations")
