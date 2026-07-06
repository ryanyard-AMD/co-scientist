"""Approved Experiment Card -> RunRequest submission (CS-EPIC-APPROVAL).

When an Experiment Card is approved, the co-scientist hands it to the external
Experimentation System as one or more RunRequests. The co-scientist never
executes; it records references (ExecutionBatchReference / RunRequestReference)
and the approval policy that governs the runs, then tracks status via
CS-EPIC-EXECUTION rollups.

The actual call to the Experimentation System RunRequest API is abstracted
behind ``run_request_submitter`` so it can be swapped for a live client once
that API exists; the default generates an external-style RunRequest ID.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from coscientist.models.experiment import ExperimentCard
from coscientist.schemas.approval import (
    ApprovalModeEnum,
    SubmissionRequest,
    SubmissionResponse,
    SubmittedRunRequest,
)
from coscientist.schemas.execution import RunRequestStatusEnum
from coscientist.schemas.experiment import ExperimentStatusEnum
from coscientist.schemas.governance import ExecutionAuditActionEnum
from coscientist.services import execution as execution_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import governance as governance_svc


def _default_run_request_submitter(payload: dict) -> str:
    """Stand-in for the Experimentation System RunRequest API call.

    Returns the external RunRequest ID. Swap/monkeypatch this for a live client.
    """
    return f"rr-{uuid.uuid4().hex}"


run_request_submitter = _default_run_request_submitter


def _run_status_for_mode(
    mode: ApprovalModeEnum, total: int, threshold: int | None
) -> RunRequestStatusEnum:
    if mode == ApprovalModeEnum.approve_each_run:
        return RunRequestStatusEnum.blocked
    if mode == ApprovalModeEnum.approval_required_above_threshold:
        if threshold is not None and total > threshold:
            return RunRequestStatusEnum.blocked
    return RunRequestStatusEnum.pending


def _build_approval_policy(
    card: ExperimentCard, body: SubmissionRequest, approval_id: str
) -> dict:
    capabilities = json.loads(card.required_capabilities) if card.required_capabilities else []
    resource_policy = {"required_capabilities": capabilities, **body.resource_policy}
    return {
        "approval_id": approval_id,
        "approver": body.approver,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approval_mode": body.approval_mode.value,
        "approval_threshold": body.approval_threshold,
        "cost_class": body.cost_class or card.estimated_cost,
        "credentialed": body.credentialed,
        "resource_policy": resource_policy,
        "retry_policy": body.retry_policy,
    }


def submit_experiment(
    db: Session,
    experiment_id: str,
    goal_id: str,
    body: SubmissionRequest,
) -> SubmissionResponse:
    card = db.get(ExperimentCard, experiment_id)
    if card is None or card.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found")
    if card.status != ExperimentStatusEnum.approved.value:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment must be 'approved' to submit, got {card.status!r}",
        )
    if card.execution_batch_id:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment {experiment_id!r} already submitted as batch {card.execution_batch_id!r}",
        )

    preview = experiment_svc.preview_run_requests(db, experiment_id, cap=body.cap)
    total = len(preview.runs)
    approval_id = str(uuid.uuid4())
    policy = _build_approval_policy(card, body, approval_id)
    run_status = _run_status_for_mode(body.approval_mode, total, body.approval_threshold)

    card.handoff_status = "submitting"
    db.flush()

    batch = execution_svc.create_execution_batch(
        db,
        experiment_id=experiment_id,
        goal_id=goal_id,
        workspace_id=card.workspace_id,
        submission_mode=card.submission_mode,
        submitter=body.approver,
        approval_policy=policy,
        control_plane_uri=card.experiment_control_plane,
        commit=False,
    )
    db.flush()

    submitted: list[SubmittedRunRequest] = []
    run_request_ids: list[str] = []
    for item in preview.runs:
        payload = {
            "experiment_id": experiment_id,
            "parameters": item.parameters,
            "approval_policy": policy,
            "correlation_id": batch.correlation_id,
        }
        rr_id = run_request_submitter(payload)
        execution_svc.register_run_request(
            db,
            run_request_id=rr_id,
            experiment_id=experiment_id,
            goal_id=goal_id,
            workspace_id=card.workspace_id,
            execution_batch_id=batch.id,
            correlation_id=batch.correlation_id,
            parameters=item.parameters,
            control_plane_uri=card.experiment_control_plane,
            status=run_status,
            commit=False,
        )
        run_request_ids.append(rr_id)
        submitted.append(
            SubmittedRunRequest(
                run_request_id=rr_id, status=run_status.value, parameters=item.parameters
            )
        )

    card.execution_batch_id = batch.id
    card.run_request_ids = json.dumps(run_request_ids)
    card.handoff_status = "submitted"
    db.flush()

    batch = execution_svc.recompute_batch(db, batch.id)

    governance_svc.record_execution_event(
        db,
        workspace_id=card.workspace_id,
        action=ExecutionAuditActionEnum.handoff_submitted,
        actor=body.approver or governance_svc.HANDOFF_AGENT_NAME,
        experiment_id=experiment_id,
        execution_batch_id=batch.id,
        approval_id=approval_id,
        run_request_ids=run_request_ids,
        policy=policy,
        payload_checksum=governance_svc.payload_checksum(
            {
                "experiment_id": experiment_id,
                "run_request_ids": run_request_ids,
                "approval_policy": policy,
            }
        ),
        detail={"submission_mode": card.submission_mode, "run_request_count": total},
    )

    db.commit()
    db.refresh(card)

    return SubmissionResponse(
        experiment_id=experiment_id,
        execution_batch_id=batch.id,
        approval_mode=body.approval_mode,
        handoff_status=card.handoff_status,
        execution_status=card.execution_status,
        aggregate_status=batch.aggregate_status,
        run_request_count=len(submitted),
        runs=submitted,
    )
