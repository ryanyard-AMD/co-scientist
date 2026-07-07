"""Execution batch / RunRequest / RunAttempt tracking (CS-EPIC-EXECUTION).

The co-scientist does not execute experiments — it hands approved cards to the
external Experimentation System and keeps *references* to the batches, run
requests, and attempts that system owns. Status updates arrive by poll or
webhook and are rolled up into an aggregate batch status and the Experiment
Card's execution_status.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coscientist.models.execution import (
    ExecutionBatchReference,
    RunAttemptReference,
    RunRequestReference,
)
from coscientist.schemas.execution import (
    BatchAggregateStatusEnum,
    BatchStatusCounts,
    ExecutionBatchReferenceResponse,
    RunAttemptCreate,
    RunAttemptReferenceResponse,
    RunAttemptStatusEnum,
    RunRequestReferenceResponse,
    RunRequestStatusEnum,
    RunStatusUpdate,
)
from coscientist.schemas.experiment import ExecutionStatusEnum
from coscientist.schemas.governance import ExecutionAuditActionEnum
from coscientist.services import experiment as experiment_svc
from coscientist.services import governance as governance_svc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_correlation_id() -> str:
    return f"corr-{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _batch_to_response(b: ExecutionBatchReference) -> ExecutionBatchReferenceResponse:
    return ExecutionBatchReferenceResponse(
        id=b.id,
        workspace_id=b.workspace_id,
        experiment_id=b.experiment_id,
        goal_id=b.goal_id,
        correlation_id=b.correlation_id,
        submission_mode=b.submission_mode,
        aggregate_status=BatchAggregateStatusEnum(b.aggregate_status),
        approval_policy=json.loads(b.approval_policy) if b.approval_policy else {},
        submitter=b.submitter,
        control_plane_uri=b.control_plane_uri,
        counts=BatchStatusCounts(
            total=b.total_count,
            queued=b.queued_count,
            running=b.running_count,
            completed=b.completed_count,
            failed=b.failed_count,
            canceled=b.canceled_count,
            blocked=b.blocked_count,
            timed_out=b.timed_out_count,
        ),
        submitted_at=b.submitted_at,
        updated_at=b.updated_at,
    )


def _run_to_response(r: RunRequestReference) -> RunRequestReferenceResponse:
    return RunRequestReferenceResponse(
        id=r.id,
        run_request_id=r.run_request_id,
        workspace_id=r.workspace_id,
        experiment_id=r.experiment_id,
        goal_id=r.goal_id,
        execution_batch_id=r.execution_batch_id,
        correlation_id=r.correlation_id,
        hypothesis_id=r.hypothesis_id,
        approach_ids=json.loads(r.approach_ids) if r.approach_ids else [],
        status=RunRequestStatusEnum(r.status),
        control_plane_uri=r.control_plane_uri,
        parameters=json.loads(r.parameters) if r.parameters else {},
        submitted_at=r.submitted_at,
        latest_update_at=r.latest_update_at,
    )


def _attempt_to_response(a: RunAttemptReference) -> RunAttemptReferenceResponse:
    return RunAttemptReferenceResponse(
        id=a.id,
        attempt_id=a.attempt_id,
        run_request_id=a.run_request_id,
        runner_id=a.runner_id,
        status=RunAttemptStatusEnum(a.status),
        failure_summary=a.failure_summary,
        started_at=a.started_at,
        finished_at=a.finished_at,
        created_at=a.created_at,
    )


# ---------------------------------------------------------------------------
# Creation (driven by the approval / handoff flow)
# ---------------------------------------------------------------------------

def create_execution_batch(
    db: Session,
    *,
    experiment_id: str,
    goal_id: str,
    workspace_id: str,
    submission_mode: str,
    submitter: str | None = None,
    approval_policy: dict | None = None,
    control_plane_uri: str | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> ExecutionBatchReference:
    batch = ExecutionBatchReference(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        experiment_id=experiment_id,
        goal_id=goal_id,
        correlation_id=correlation_id or new_correlation_id(),
        submission_mode=submission_mode,
        aggregate_status=BatchAggregateStatusEnum.submitted.value,
        approval_policy=json.dumps(approval_policy or {}),
        submitter=submitter,
        control_plane_uri=control_plane_uri,
        submitted_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(batch)
    if commit:
        db.commit()
        db.refresh(batch)
    return batch


def register_run_request(
    db: Session,
    *,
    run_request_id: str,
    experiment_id: str,
    goal_id: str,
    workspace_id: str,
    execution_batch_id: str | None = None,
    correlation_id: str | None = None,
    hypothesis_id: str | None = None,
    approach_ids: list[str] | None = None,
    parameters: dict | None = None,
    control_plane_uri: str | None = None,
    status: RunRequestStatusEnum = RunRequestStatusEnum.pending,
    commit: bool = True,
) -> RunRequestReference:
    existing = db.scalar(
        select(RunRequestReference).where(RunRequestReference.run_request_id == run_request_id)
    )
    if existing is not None:
        # Idempotent: registering the same RunRequest twice returns the first.
        return existing
    ref = RunRequestReference(
        id=str(uuid.uuid4()),
        run_request_id=run_request_id,
        workspace_id=workspace_id,
        experiment_id=experiment_id,
        goal_id=goal_id,
        execution_batch_id=execution_batch_id,
        correlation_id=correlation_id or new_correlation_id(),
        hypothesis_id=hypothesis_id,
        approach_ids=json.dumps(approach_ids or []),
        status=status.value,
        control_plane_uri=control_plane_uri,
        parameters=json.dumps(parameters or {}),
        submitted_at=_utcnow(),
        latest_update_at=_utcnow(),
    )
    db.add(ref)
    if commit:
        db.commit()
        db.refresh(ref)
    if execution_batch_id:
        recompute_batch(db, execution_batch_id)
    return ref


# ---------------------------------------------------------------------------
# Status ingestion + rollup
# ---------------------------------------------------------------------------

def _get_run_or_404(db: Session, run_request_id: str) -> RunRequestReference:
    ref = db.scalar(
        select(RunRequestReference).where(RunRequestReference.run_request_id == run_request_id)
    )
    if ref is None:
        raise HTTPException(status_code=404, detail=f"RunRequest {run_request_id!r} not found")
    return ref


def apply_run_status_update(
    db: Session, run_request_id: str, update: RunStatusUpdate
) -> RunRequestReferenceResponse:
    ref = _get_run_or_404(db, run_request_id)
    ref.status = update.status.value
    ref.latest_update_at = _utcnow()
    governance_svc.record_execution_event(
        db,
        workspace_id=ref.workspace_id,
        action=ExecutionAuditActionEnum.run_status_updated,
        experiment_id=ref.experiment_id,
        execution_batch_id=ref.execution_batch_id,
        run_request_ids=[run_request_id],
        detail={"status": update.status.value},
    )
    db.commit()
    db.refresh(ref)
    if ref.execution_batch_id:
        recompute_batch(db, ref.execution_batch_id)
    else:
        _sync_experiment_execution_status(db, ref.experiment_id, _run_status_to_execution(update.status))
    return _run_to_response(ref)


_TERMINAL = {
    RunRequestStatusEnum.completed,
    RunRequestStatusEnum.failed,
    RunRequestStatusEnum.canceled,
    RunRequestStatusEnum.timed_out,
}


def _run_status_to_execution(status: RunRequestStatusEnum) -> ExecutionStatusEnum:
    return {
        RunRequestStatusEnum.pending: ExecutionStatusEnum.submitted,
        RunRequestStatusEnum.queued: ExecutionStatusEnum.queued,
        RunRequestStatusEnum.running: ExecutionStatusEnum.running,
        RunRequestStatusEnum.completed: ExecutionStatusEnum.completed,
        RunRequestStatusEnum.failed: ExecutionStatusEnum.failed,
        RunRequestStatusEnum.canceled: ExecutionStatusEnum.blocked,
        RunRequestStatusEnum.blocked: ExecutionStatusEnum.blocked,
        RunRequestStatusEnum.timed_out: ExecutionStatusEnum.failed,
    }[status]


def _aggregate_status(counts: dict[str, int]) -> BatchAggregateStatusEnum:
    total = counts["total"]
    if total == 0:
        return BatchAggregateStatusEnum.submitted
    completed = counts["completed"]
    failed = counts["failed"] + counts["timed_out"]
    canceled = counts["canceled"]
    running = counts["running"]
    queued = counts["queued"]
    blocked = counts["blocked"]
    terminal = completed + failed + canceled

    if terminal >= total:
        if completed == total:
            return BatchAggregateStatusEnum.completed
        if canceled == total:
            return BatchAggregateStatusEnum.canceled
        if completed == 0 and failed > 0:
            return BatchAggregateStatusEnum.failed
        return BatchAggregateStatusEnum.mixed_outcome

    # some runs are still non-terminal
    if running > 0:
        if completed > 0 or failed > 0:
            return BatchAggregateStatusEnum.partially_completed
        return BatchAggregateStatusEnum.running
    if completed > 0 or failed > 0:
        return BatchAggregateStatusEnum.partially_completed
    if queued > 0:
        return BatchAggregateStatusEnum.queued
    if blocked > 0:
        return BatchAggregateStatusEnum.blocked
    return BatchAggregateStatusEnum.submitted


_BATCH_TO_EXECUTION = {
    BatchAggregateStatusEnum.submitted: ExecutionStatusEnum.submitted,
    BatchAggregateStatusEnum.queued: ExecutionStatusEnum.queued,
    BatchAggregateStatusEnum.running: ExecutionStatusEnum.running,
    BatchAggregateStatusEnum.partially_completed: ExecutionStatusEnum.partially_completed,
    BatchAggregateStatusEnum.completed: ExecutionStatusEnum.completed,
    BatchAggregateStatusEnum.failed: ExecutionStatusEnum.failed,
    BatchAggregateStatusEnum.mixed_outcome: ExecutionStatusEnum.mixed_outcome,
    BatchAggregateStatusEnum.blocked: ExecutionStatusEnum.blocked,
    BatchAggregateStatusEnum.canceled: ExecutionStatusEnum.blocked,
}


def recompute_batch(db: Session, batch_id: str) -> ExecutionBatchReference:
    batch = db.get(ExecutionBatchReference, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"ExecutionBatch {batch_id!r} not found")
    runs = db.scalars(
        select(RunRequestReference).where(RunRequestReference.execution_batch_id == batch_id)
    ).all()
    counts = {
        "total": len(runs), "queued": 0, "running": 0, "completed": 0,
        "failed": 0, "canceled": 0, "blocked": 0, "timed_out": 0,
    }
    for r in runs:
        if r.status in counts:
            counts[r.status] += 1
    batch.total_count = counts["total"]
    batch.queued_count = counts["queued"]
    batch.running_count = counts["running"]
    batch.completed_count = counts["completed"]
    batch.failed_count = counts["failed"]
    batch.canceled_count = counts["canceled"]
    batch.blocked_count = counts["blocked"]
    batch.timed_out_count = counts["timed_out"]
    agg = _aggregate_status(counts)
    batch.aggregate_status = agg.value
    batch.updated_at = _utcnow()
    db.commit()
    db.refresh(batch)
    _sync_experiment_execution_status(db, batch.experiment_id, _BATCH_TO_EXECUTION[agg])
    return batch


def _sync_experiment_execution_status(db: Session, experiment_id: str, status: ExecutionStatusEnum) -> None:
    try:
        experiment_svc.set_execution_status(db, experiment_id, status, force=True)
    except HTTPException:
        # Experiment card may have been archived/removed; status sync is best-effort.
        pass


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------

def record_run_attempt(
    db: Session, run_request_id: str, data: RunAttemptCreate
) -> RunAttemptReferenceResponse:
    _get_run_or_404(db, run_request_id)
    attempt = RunAttemptReference(
        id=str(uuid.uuid4()),
        attempt_id=data.attempt_id,
        run_request_id=run_request_id,
        runner_id=data.runner_id,
        status=data.status.value,
        failure_summary=data.failure_summary,
        started_at=data.started_at,
        finished_at=data.finished_at,
        created_at=_utcnow(),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return _attempt_to_response(attempt)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_batch(db: Session, batch_id: str) -> ExecutionBatchReferenceResponse:
    batch = db.get(ExecutionBatchReference, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"ExecutionBatch {batch_id!r} not found")
    return _batch_to_response(batch)


def list_batches(db: Session, goal_id: str, *, skip: int = 0, limit: int = 20) -> tuple[list[ExecutionBatchReferenceResponse], int]:
    q = select(ExecutionBatchReference).where(ExecutionBatchReference.goal_id == goal_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(ExecutionBatchReference.submitted_at.desc()).offset(skip).limit(limit)).all()
    return [_batch_to_response(r) for r in rows], total


def list_run_requests(db: Session, *, batch_id: str | None = None, experiment_id: str | None = None) -> tuple[list[RunRequestReferenceResponse], int]:
    q = select(RunRequestReference)
    if batch_id is not None:
        q = q.where(RunRequestReference.execution_batch_id == batch_id)
    if experiment_id is not None:
        q = q.where(RunRequestReference.experiment_id == experiment_id)
    rows = db.scalars(q.order_by(RunRequestReference.submitted_at)).all()
    return [_run_to_response(r) for r in rows], len(rows)


def get_run_request(db: Session, run_request_id: str) -> RunRequestReferenceResponse:
    return _run_to_response(_get_run_or_404(db, run_request_id))


def list_attempts(db: Session, run_request_id: str) -> tuple[list[RunAttemptReferenceResponse], int]:
    _get_run_or_404(db, run_request_id)
    rows = db.scalars(
        select(RunAttemptReference)
        .where(RunAttemptReference.run_request_id == run_request_id)
        .order_by(RunAttemptReference.created_at)
    ).all()
    return [_attempt_to_response(r) for r in rows], len(rows)
