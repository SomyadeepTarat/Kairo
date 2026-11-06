"""Create the M3 execution history tables.

Revision ID: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("current_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model_configuration", postgresql.JSONB(), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("output", sa.Text()),
        sa.Column("error", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('CREATED','QUEUED','RUNNING','WAITING_FOR_TOOL',"
            "'WAITING_FOR_APPROVAL','PAUSED','COMPLETED','FAILED','CANCELLED')",
            name="ck_run_status",
        ),
        sa.CheckConstraint("event_sequence >= 0", name="ck_run_sequence"),
    )
    op.create_index("ix_runs_created_id", "runs", ["created_at", "id"])
    op.create_table(
        "run_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.Text()),
        sa.UniqueConstraint("run_id", "id", name="uq_attempt_run_id"),
    )
    op.create_foreign_key(
        "fk_run_current_attempt",
        "runs",
        "run_attempts",
        ["current_attempt_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "execution_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("run_attempts.id"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence_number", name="uq_event_run_sequence"),
        sa.CheckConstraint("sequence_number > 0", name="ck_event_sequence"),
    )
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("run_attempts.id"), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("output_json", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("side_effect_class", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("outcome_uncertain", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tools_run_started_id", "tool_executions", ["run_id", "started_at", "id"])


def downgrade() -> None:
    op.drop_table("tool_executions")
    op.drop_table("execution_events")
    op.drop_constraint("fk_run_current_attempt", "runs", type_="foreignkey")
    op.drop_table("run_attempts")
    op.drop_table("runs")
    op.drop_table("tasks")
