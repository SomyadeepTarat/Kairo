"""Durable queue and worker leases.

Revision ID: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("capacity > 0 AND capacity <= 32", name="ck_worker_capacity"),
    )
    op.create_table(
        "jobs",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("worker_id", sa.Uuid(), sa.ForeignKey("workers.id")),
        sa.Column("token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "state IN ('QUEUED','CLAIMED','REAPING','DONE','FAILED','CANCELLED')",
            name="ck_job_state",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_job_attempts"),
    )
    op.create_index("ix_jobs_available", "jobs", ["state", "available_at", "run_id"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("workers")
