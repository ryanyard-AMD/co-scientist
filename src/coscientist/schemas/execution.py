from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunRequestStatusEnum(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"
    blocked = "blocked"
    timed_out = "timed_out"


class BatchAggregateStatusEnum(str, Enum):
    submitted = "submitted"
    queued = "queued"
    running = "running"
    partially_completed = "partially_completed"
    completed = "completed"
    failed = "failed"
    mixed_outcome = "mixed_outcome"
    blocked = "blocked"
    canceled = "canceled"


class RunAttemptStatusEnum(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    retrying = "retrying"
    canceled = "canceled"


class BatchStatusCounts(BaseModel):
    total: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    canceled: int = 0
    blocked: int = 0
    timed_out: int = 0


class RunRequestReferenceResponse(BaseModel):
    id: str
    run_request_id: str
    workspace_id: str
    experiment_id: str
    goal_id: str
    execution_batch_id: str | None
    correlation_id: str
    status: RunRequestStatusEnum
    control_plane_uri: str | None
    parameters: dict[str, Any]
    submitted_at: datetime
    latest_update_at: datetime


class RunAttemptReferenceResponse(BaseModel):
    id: str
    attempt_id: str
    run_request_id: str
    runner_id: str | None
    status: RunAttemptStatusEnum
    failure_summary: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ExecutionBatchReferenceResponse(BaseModel):
    id: str
    workspace_id: str
    experiment_id: str
    goal_id: str
    correlation_id: str
    submission_mode: str
    aggregate_status: BatchAggregateStatusEnum
    approval_policy: dict[str, Any]
    submitter: str | None
    control_plane_uri: str | None
    counts: BatchStatusCounts
    submitted_at: datetime
    updated_at: datetime


class ExecutionBatchListResponse(BaseModel):
    items: list[ExecutionBatchReferenceResponse]
    total: int


class RunRequestListResponse(BaseModel):
    items: list[RunRequestReferenceResponse]
    total: int


class RunAttemptListResponse(BaseModel):
    items: list[RunAttemptReferenceResponse]
    total: int


class ExecutionBatchCreate(BaseModel):
    """Create a co-scientist-side reference to an ExecutionBatch at handoff time."""

    experiment_id: str
    goal_id: str
    workspace_id: str
    submission_mode: str = "single_run"
    submitter: str | None = None
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    control_plane_uri: str | None = None
    correlation_id: str | None = None


class RunRequestRegister(BaseModel):
    """Register a RunRequest reference (optionally attached to a batch)."""

    run_request_id: str
    experiment_id: str
    goal_id: str
    workspace_id: str
    execution_batch_id: str | None = None
    correlation_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    control_plane_uri: str | None = None
    status: RunRequestStatusEnum = RunRequestStatusEnum.pending


class RunStatusUpdate(BaseModel):
    """Status update ingested from the Experimentation System (poll or webhook)."""

    status: RunRequestStatusEnum
    runner_id: str | None = None
    detail: str | None = None


class RunAttemptCreate(BaseModel):
    attempt_id: str
    status: RunAttemptStatusEnum = RunAttemptStatusEnum.running
    runner_id: str | None = None
    failure_summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
