"""Checkpointed continuation and bounded recovery.

Revision ID: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3")
    )
    op.alter_column("jobs", "max_attempts", server_default=None)
    op.add_column("jobs", sa.Column("blocked_reason", sa.Text()))
    op.add_column("jobs", sa.Column("resume_state", postgresql.JSONB()))
    op.drop_constraint("ck_job_state", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_state",
        "jobs",
        "state IN ('QUEUED','CLAIMED','REAPING','DONE','FAILED','CANCELLED','BLOCKED')",
    )
    op.create_check_constraint(
        "ck_job_max_attempts", "jobs", "max_attempts >= 1 AND max_attempts <= 10"
    )
    op.create_table(
        "checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("run_attempts.id"), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("workspace_reference", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "event_sequence", name="uq_checkpoint_run_sequence"),
    )


def downgrade() -> None:
    # Only downgrade disposable/empty schemas: active blocked work must not be erased.
    op.execute("UPDATE jobs SET state='FAILED' WHERE state='BLOCKED'")
    op.drop_table("checkpoints")
    op.drop_constraint("ck_job_max_attempts", "jobs", type_="check")
    op.drop_constraint("ck_job_state", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_state",
        "jobs",
        "state IN ('QUEUED','CLAIMED','REAPING','DONE','FAILED','CANCELLED')",
    )
    op.drop_column("jobs", "resume_state")
    op.drop_column("jobs", "blocked_reason")
    op.drop_column("jobs", "max_attempts")
