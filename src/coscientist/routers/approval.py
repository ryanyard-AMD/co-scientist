from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.approval import (
    ApprovalActionBody,
    ApprovalDecisionCreate,
    ApprovalDecisionEnum,
    ApprovalDecisionListResponse,
    ApprovalDecisionResponse,
    ExperimentDuplicateResponse,
    SubmissionRequest,
    SubmissionResponse,
)
from coscientist.schemas.experiment import ExperimentCardResponse
from coscientist.schemas.handoff import (
    HandoffControlBody,
    HandoffRequestListResponse,
    HandoffRequestResponse,
)
from coscientist.services import approval as svc
from coscientist.services import handoff as handoff_svc
from coscientist.services import submission as submission_svc

router = APIRouter(prefix="/goals/{goal_id}/experiments", tags=["approval"])


@router.get("/pending", response_model=list[ExperimentCardResponse])
def list_pending(
    goal_id: str,
    filter_goal: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    actual_goal_id = goal_id if filter_goal else None
    return svc.list_pending(db, goal_id=actual_goal_id)


@router.post("/{experiment_id}/approve", response_model=ApprovalDecisionResponse, status_code=201)
def approve_experiment(
    goal_id: str,
    experiment_id: str,
    body: ApprovalActionBody,
    db: Session = Depends(get_db),
):
    decision_body = ApprovalDecisionCreate(
        decision=ApprovalDecisionEnum.approve,
        reviewer_id=body.reviewer_id,
        reason=body.reason,
        resource_flags=body.resource_flags,
    )
    return svc.record_decision(db, experiment_id, goal_id, decision_body)


@router.post("/{experiment_id}/reject", response_model=ApprovalDecisionResponse, status_code=201)
def reject_experiment(
    goal_id: str,
    experiment_id: str,
    body: ApprovalActionBody,
    db: Session = Depends(get_db),
):
    try:
        decision_body = ApprovalDecisionCreate(
            decision=ApprovalDecisionEnum.reject,
            reviewer_id=body.reviewer_id,
            reason=body.reason,
            resource_flags=body.resource_flags,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return svc.record_decision(db, experiment_id, goal_id, decision_body)


@router.post("/{experiment_id}/request-edit", response_model=ApprovalDecisionResponse, status_code=201)
def request_edit_experiment(
    goal_id: str,
    experiment_id: str,
    body: ApprovalActionBody,
    db: Session = Depends(get_db),
):
    try:
        decision_body = ApprovalDecisionCreate(
            decision=ApprovalDecisionEnum.request_edit,
            reviewer_id=body.reviewer_id,
            reason=body.reason,
            resource_flags=body.resource_flags,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return svc.record_decision(db, experiment_id, goal_id, decision_body)


@router.post("/{experiment_id}/duplicate", response_model=ExperimentDuplicateResponse, status_code=201)
def duplicate_experiment(
    goal_id: str,
    experiment_id: str,
    db: Session = Depends(get_db),
):
    return svc.duplicate_experiment(db, experiment_id, goal_id)


@router.post("/{experiment_id}/submit", response_model=SubmissionResponse, status_code=201)
def submit_experiment(
    goal_id: str,
    experiment_id: str,
    body: SubmissionRequest | None = None,
    db: Session = Depends(get_db),
):
    return submission_svc.submit_experiment(
        db, experiment_id, goal_id, body or SubmissionRequest()
    )


@router.post("/{experiment_id}/retry", response_model=SubmissionResponse, status_code=201)
def retry_submit_experiment(
    goal_id: str,
    experiment_id: str,
    body: SubmissionRequest | None = None,
    db: Session = Depends(get_db),
):
    """Retry a failed handoff. Reuses the existing batch and does not create
    duplicate RunRequests for runs already handed off (CS-APPROVAL-010)."""
    return submission_svc.submit_experiment(
        db, experiment_id, goal_id, body or SubmissionRequest()
    )


@router.post("/{experiment_id}/cancel", response_model=HandoffRequestResponse, status_code=201)
def cancel_experiment(
    goal_id: str,
    experiment_id: str,
    body: HandoffControlBody | None = None,
    db: Session = Depends(get_db),
):
    body = body or HandoffControlBody()
    return handoff_svc.request_cancellation(
        db, experiment_id, goal_id, requester=body.requester, reason=body.reason
    )


@router.post("/{experiment_id}/resubmit", response_model=HandoffRequestResponse, status_code=201)
def resubmit_experiment(
    goal_id: str,
    experiment_id: str,
    body: HandoffControlBody | None = None,
    db: Session = Depends(get_db),
):
    body = body or HandoffControlBody()
    return handoff_svc.request_resubmission(
        db, experiment_id, goal_id, requester=body.requester, reason=body.reason
    )


@router.get("/{experiment_id}/handoff-requests", response_model=HandoffRequestListResponse)
def list_handoff_requests(
    goal_id: str,
    experiment_id: str,
    db: Session = Depends(get_db),
):
    return handoff_svc.list_handoff_requests(db, experiment_id)


@router.get("/{experiment_id}/decisions", response_model=ApprovalDecisionListResponse)
def list_decisions(
    goal_id: str,
    experiment_id: str,
    db: Session = Depends(get_db),
):
    return svc.list_decisions(db, experiment_id, goal_id)
