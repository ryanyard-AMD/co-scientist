"""HTTP surface for execution reference tracking (CS-EPIC-EXECUTION).

The co-scientist does not run experiments. These endpoints let the approval /
handoff flow record references to ExecutionBatches and RunRequests owned by the
external Experimentation System, and ingest status updates (poll or webhook)
that roll up into an aggregate batch status and the Experiment Card's
execution_status.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.execution import (
    ExecutionBatchCreate,
    ExecutionBatchListResponse,
    ExecutionBatchReferenceResponse,
    RunAttemptCreate,
    RunAttemptListResponse,
    RunAttemptReferenceResponse,
    RunRequestListResponse,
    RunRequestReferenceResponse,
    RunRequestRegister,
    RunStatusUpdate,
)
from coscientist.services import execution as svc

router = APIRouter(tags=["execution"])


@router.post("/execution-batches", response_model=ExecutionBatchReferenceResponse, status_code=201)
def create_batch(body: ExecutionBatchCreate, db: Session = Depends(get_db)):
    batch = svc.create_execution_batch(
        db,
        experiment_id=body.experiment_id,
        goal_id=body.goal_id,
        workspace_id=body.workspace_id,
        submission_mode=body.submission_mode,
        submitter=body.submitter,
        approval_policy=body.approval_policy,
        control_plane_uri=body.control_plane_uri,
        correlation_id=body.correlation_id,
    )
    return svc.get_batch(db, batch.id)


@router.get("/goals/{goal_id}/execution-batches", response_model=ExecutionBatchListResponse)
def list_batches(goal_id: str, skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    items, total = svc.list_batches(db, goal_id, skip=skip, limit=limit)
    return ExecutionBatchListResponse(items=items, total=total)


@router.get("/execution-batches/{batch_id}", response_model=ExecutionBatchReferenceResponse)
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    return svc.get_batch(db, batch_id)


@router.post("/run-requests", response_model=RunRequestReferenceResponse, status_code=201)
def register_run_request(body: RunRequestRegister, db: Session = Depends(get_db)):
    ref = svc.register_run_request(
        db,
        run_request_id=body.run_request_id,
        experiment_id=body.experiment_id,
        goal_id=body.goal_id,
        workspace_id=body.workspace_id,
        execution_batch_id=body.execution_batch_id,
        correlation_id=body.correlation_id,
        parameters=body.parameters,
        control_plane_uri=body.control_plane_uri,
        status=body.status,
    )
    return svc.get_run_request(db, ref.run_request_id)


@router.get("/run-requests", response_model=RunRequestListResponse)
def list_run_requests(
    batch_id: str | None = None,
    experiment_id: str | None = None,
    db: Session = Depends(get_db),
):
    items, total = svc.list_run_requests(db, batch_id=batch_id, experiment_id=experiment_id)
    return RunRequestListResponse(items=items, total=total)


@router.get("/run-requests/{run_request_id}", response_model=RunRequestReferenceResponse)
def get_run_request(run_request_id: str, db: Session = Depends(get_db)):
    return svc.get_run_request(db, run_request_id)


@router.post("/run-requests/{run_request_id}/status", response_model=RunRequestReferenceResponse)
def apply_status(run_request_id: str, body: RunStatusUpdate, db: Session = Depends(get_db)):
    return svc.apply_run_status_update(db, run_request_id, body)


@router.post(
    "/run-requests/{run_request_id}/attempts",
    response_model=RunAttemptReferenceResponse,
    status_code=201,
)
def record_attempt(run_request_id: str, body: RunAttemptCreate, db: Session = Depends(get_db)):
    return svc.record_run_attempt(db, run_request_id, body)


@router.get("/run-requests/{run_request_id}/attempts", response_model=RunAttemptListResponse)
def list_attempts(run_request_id: str, db: Session = Depends(get_db)):
    items, total = svc.list_attempts(db, run_request_id)
    return RunAttemptListResponse(items=items, total=total)
