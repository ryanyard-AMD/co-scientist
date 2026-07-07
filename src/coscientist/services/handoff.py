"""Handoff control: failed-handoff records, retries, and cancel/resubmit
requests against the external Experimentation System (CS-APPROVAL-010/011).

The co-scientist never controls execution. It records that a control action was
requested and the status the Experimentation System reported. The actual
starting, stopping, and re-running of experiments is owned by that system; these
functions only relay a request and persist a reference to it.

The external calls are abstracted behind ``cancellation_requester`` /
``resubmission_requester`` so they can be swapped for a live client; the defaults
return a request status of ``"requested"``.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.experiment import ExperimentCard
from coscientist.models.handoff import HandoffRequest
from coscientist.schemas.governance import ExecutionAuditActionEnum
from coscientist.schemas.handoff import (
    HandoffRequestListResponse,
    HandoffRequestResponse,
    HandoffRequestStatusEnum,
    HandoffRequestTypeEnum,
)
from coscientist.services import governance as governance_svc


def _default_cancellation_requester(payload: dict) -> str:
    """Stand-in for the Experimentation System cancellation API. Returns the
    request status. Swap/monkeypatch this for a live client."""
    return HandoffRequestStatusEnum.requested.value


def _default_resubmission_requester(payload: dict) -> str:
    """Stand-in for the Experimentation System resubmission API. Returns the
    request status. Swap/monkeypatch this for a live client."""
    return HandoffRequestStatusEnum.requested.value


cancellation_requester = _default_cancellation_requester
resubmission_requester = _default_resubmission_requester


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_response(row: HandoffRequest) -> HandoffRequestResponse:
    return HandoffRequestResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        experiment_id=row.experiment_id,
        goal_id=row.goal_id,
        request_type=HandoffRequestTypeEnum(row.request_type),
        status=HandoffRequestStatusEnum(row.status),
        error=row.error,
        payload_summary=json.loads(row.payload_summary) if row.payload_summary else None,
        approval_id=row.approval_id,
        retryable=row.retryable,
        run_request_ids=json.loads(row.run_request_ids) if row.run_request_ids else [],
        execution_batch_id=row.execution_batch_id,
        correlation_id=row.correlation_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def record_handoff_request(
    db: Session,
    *,
    workspace_id: str,
    experiment_id: str,
    goal_id: str,
    request_type: HandoffRequestTypeEnum,
    status: HandoffRequestStatusEnum,
    error: str | None = None,
    payload_summary: dict | None = None,
    approval_id: str | None = None,
    retryable: bool = False,
    run_request_ids: list[str] | None = None,
    execution_batch_id: str | None = None,
    correlation_id: str | None = None,
    commit: bool = False,
) -> HandoffRequest:
    row = HandoffRequest(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        experiment_id=experiment_id,
        goal_id=goal_id,
        request_type=request_type.value,
        status=status.value,
        error=error,
        payload_summary=json.dumps(payload_summary, default=str) if payload_summary is not None else None,
        approval_id=approval_id,
        retryable=retryable,
        run_request_ids=json.dumps(run_request_ids or []),
        execution_batch_id=execution_batch_id,
        correlation_id=correlation_id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


def _get_card_or_404(db: Session, experiment_id: str, goal_id: str) -> ExperimentCard:
    card = db.get(ExperimentCard, experiment_id)
    if card is None or card.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found")
    return card


def _require_submitted(card: ExperimentCard) -> None:
    if not card.execution_batch_id:
        raise HTTPException(
            status_code=409,
            detail="Experiment has not been submitted to the Experimentation System",
        )


def request_cancellation(
    db: Session, experiment_id: str, goal_id: str, *, requester: str | None = None, reason: str | None = None
) -> HandoffRequestResponse:
    card = _get_card_or_404(db, experiment_id, goal_id)
    _require_submitted(card)
    run_request_ids = json.loads(card.run_request_ids) if card.run_request_ids else []
    payload = {
        "experiment_id": experiment_id,
        "execution_batch_id": card.execution_batch_id,
        "run_request_ids": run_request_ids,
        "reason": reason,
    }
    status_value = cancellation_requester(payload)
    row = record_handoff_request(
        db,
        workspace_id=card.workspace_id,
        experiment_id=experiment_id,
        goal_id=goal_id,
        request_type=HandoffRequestTypeEnum.cancel,
        status=HandoffRequestStatusEnum(status_value),
        payload_summary={"reason": reason, "run_request_count": len(run_request_ids)},
        run_request_ids=run_request_ids,
        execution_batch_id=card.execution_batch_id,
    )
    governance_svc.record_execution_event(
        db,
        workspace_id=card.workspace_id,
        action=ExecutionAuditActionEnum.cancellation_requested,
        actor=requester or governance_svc.HANDOFF_AGENT_NAME,
        experiment_id=experiment_id,
        execution_batch_id=card.execution_batch_id,
        run_request_ids=run_request_ids,
        detail={"status": status_value, "reason": reason},
    )
    db.commit()
    db.refresh(row)
    return _to_response(row)


def request_resubmission(
    db: Session, experiment_id: str, goal_id: str, *, requester: str | None = None, reason: str | None = None
) -> HandoffRequestResponse:
    card = _get_card_or_404(db, experiment_id, goal_id)
    _require_submitted(card)
    run_request_ids = json.loads(card.run_request_ids) if card.run_request_ids else []
    payload = {
        "experiment_id": experiment_id,
        "execution_batch_id": card.execution_batch_id,
        "run_request_ids": run_request_ids,
        "reason": reason,
    }
    status_value = resubmission_requester(payload)
    row = record_handoff_request(
        db,
        workspace_id=card.workspace_id,
        experiment_id=experiment_id,
        goal_id=goal_id,
        request_type=HandoffRequestTypeEnum.resubmit,
        status=HandoffRequestStatusEnum(status_value),
        payload_summary={"reason": reason, "run_request_count": len(run_request_ids)},
        run_request_ids=run_request_ids,
        execution_batch_id=card.execution_batch_id,
    )
    governance_svc.record_execution_event(
        db,
        workspace_id=card.workspace_id,
        action=ExecutionAuditActionEnum.resubmission_requested,
        actor=requester or governance_svc.HANDOFF_AGENT_NAME,
        experiment_id=experiment_id,
        execution_batch_id=card.execution_batch_id,
        run_request_ids=run_request_ids,
        detail={"status": status_value, "reason": reason},
    )
    db.commit()
    db.refresh(row)
    return _to_response(row)


def list_handoff_requests(db: Session, experiment_id: str) -> HandoffRequestListResponse:
    rows = db.scalars(
        select(HandoffRequest)
        .where(HandoffRequest.experiment_id == experiment_id)
        .order_by(HandoffRequest.created_at.desc())
    ).all()
    return HandoffRequestListResponse(items=[_to_response(r) for r in rows], total=len(rows))
