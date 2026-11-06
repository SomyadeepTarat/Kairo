"""PostgreSQL tables for M3; migrations, not create_all, own schema changes."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"))
    current_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "run_attempts.id",
            name="fk_run_current_attempt",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        )
    )
    status: Mapped[str] = mapped_column(String(32))
    model_configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    event_sequence: Mapped[int] = mapped_column(Integer)
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED','QUEUED','RUNNING','WAITING_FOR_TOOL',"
            "'WAITING_FOR_APPROVAL','PAUSED','COMPLETED','FAILED','CANCELLED')",
            name="ck_run_status",
        ),
        CheckConstraint("event_sequence >= 0", name="ck_run_sequence"),
        Index("ix_runs_created_id", "created_at", "id"),
    )


class AttemptRow(Base):
    __tablename__ = "run_attempts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("run_id", "id", name="uq_attempt_run_id"),)


class EventRow(Base):
    __tablename__ = "execution_events"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"))
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("run_attempts.id"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_number", name="uq_event_run_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_event_sequence"),
    )


class ToolRow(Base):
    __tablename__ = "tool_executions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"))
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("run_attempts.id"))
    tool_name: Mapped[str] = mapped_column(String(128))
    input_json: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    side_effect_class: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    outcome_uncertain: Mapped[bool] = mapped_column(Boolean)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_tools_run_started_id", "run_id", "started_at", "id"),)
