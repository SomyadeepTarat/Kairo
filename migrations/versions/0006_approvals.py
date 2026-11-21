"""Action-specific durable approvals."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("run_attempts.id"), nullable=False),
        sa.Column("invocation_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("action", JSONB(), nullable=False),
        sa.Column("risk", sa.String(32), nullable=False),
        sa.Column("agent", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','DENIED','CONSUMED')", name="ck_approval_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("approvals")
