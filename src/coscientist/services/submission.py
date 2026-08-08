"""Approved Experiment Card -> RunRequest submission (CS-EPIC-APPROVAL).

When an Experiment Card is approved, the co-scientist hands it to the external
Experimentation System as one or more RunRequests. The co-scientist never
executes; it records references (ExecutionBatchReference / RunRequestReference)
and the approval policy that governs the runs, then tracks status via
CS-EPIC-EXECUTION rollups.

The actual call to the Experimentation System RunRequest API is abstracted
behind ``run_request_submitter``. The default calls repro's handoff-run endpoint
when a card carries a control-plane URI, and otherwise generates an
external-style RunRequest ID for offline development/tests.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.execution import ExecutionBatchReference, RunRequestReference
from coscientist.models.experiment import ExperimentCard
from coscientist.clients.repro import ReproClient
from coscientist.config import settings
from coscientist.schemas.approval import (
    ApprovalModeEnum,
    SubmissionRequest,
    SubmissionResponse,
    SubmittedRunRequest,
)
from coscientist.schemas.execution import RunRequestStatusEnum
from coscientist.schemas.experiment import ExperimentStatusEnum
from coscientist.schemas.governance import ExecutionAuditActionEnum
from coscientist.schemas.handoff import HandoffRequestStatusEnum, HandoffRequestTypeEnum
from coscientist.services import approach as approach_svc
from coscientist.services import execution as execution_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import governance as governance_svc
from coscientist.services import handoff_contract
from coscientist.services import handoff as handoff_svc
from coscientist.services import runner as runner_svc


def _default_run_request_submitter(payload: dict) -> str:
    """Stand-in for the Experimentation System RunRequest API call.

    Returns the external RunRequest ID. When the card names a control-plane URI,
    submit to repro's handoff-run endpoint; otherwise preserve the local generated
    ID used by offline tests and development flows.
    """
    control_plane_uri = payload.get("control_plane_uri")
    if control_plane_uri:
        with ReproClient(base_url=control_plane_uri) as client:
            response = client.run_handoff(
                payload,
                top_k=settings.runner_recommend_top_k,
            )
        run = response.get("run") or {}
        run_id = run.get("run_id")
        if not run_id:
            raise RuntimeError("repro handoff-run response did not include run.run_id")
        return run_id
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


def _existing_run_for_params(
    db: Session, experiment_id: str, parameters: dict
) -> RunRequestReference | None:
    """Find an already-registered RunRequest for this experiment with matching
    parameters, so a retry reuses it instead of creating a duplicate RunRequest
    against the Experimentation System (CS-APPROVAL-010)."""
    target = json.dumps(parameters, sort_keys=True)
    rows = db.scalars(
        select(RunRequestReference).where(
            RunRequestReference.experiment_id == experiment_id
        )
    ).all()
    for r in rows:
        stored = json.dumps(json.loads(r.parameters) if r.parameters else {}, sort_keys=True)
        if stored == target:
            return r
    return None


def _loads(raw: str | None, default):
    if not raw:
        return default
    return json.loads(raw)


def _method_family(db: Session, approach_ids: list[str]) -> str | None:
    """The card's method family, sent to bias the execution system's choice of
    reproduction. Preflight sends it; without it submit can select a different
    reproduction than the one preflight cleared. Single-approach only, matching
    ``runner._primary_approach``.
    """
    if len(approach_ids) != 1:
        return None
    try:
        return approach_svc.get(db, approach_ids[0]).method_family
    except HTTPException:
        return None


def _run_request_payload(
    *,
    card: ExperimentCard,
    batch: ExecutionBatchReference,
    approval_policy: dict,
    parameters: dict,
    run_index: int,
    run_count: int,
    run_status: RunRequestStatusEnum,
    method_family: str | None = None,
) -> dict:
    """Build the downstream execution contract for one RunRequest.

    The external system should be able to decide whether it can execute the run
    from this payload alone; IDs are repeated in several blocks so callbacks and
    ResultBundles can be correlated without reverse lookups.
    """
    validation = _loads(card.validation, {})
    pass_conditions = runner_svc._pass_conditions(validation.get("pass_conditions", {}))
    approach_ids = _loads(card.approach_ids, [])
    experiment = {
        "name": card.name,
        "objective": card.objective,
        "hypothesis_text": card.hypothesis_text,
        "experiment_type": card.experiment_type,
        "baseline_methods": _loads(card.baseline_methods, []),
        "fixed_assumptions": _loads(card.fixed_assumptions, {}),
        "metrics": _loads(card.metrics, []),
        "validation": validation,
        "pass_conditions": pass_conditions,
        "runtime": _loads(card.runtime, {}),
        "artifacts": _loads(card.artifacts, []),
    }
    if method_family:
        experiment["method_family"] = method_family
    return {
        "schema": "co_scientist.run_request.v1",
        "co_scientist": {
            "experiment_id": card.id,
            "goal_id": card.workspace_id,
            "workspace_id": card.workspace_id,
            "execution_batch_id": batch.id,
            "correlation_id": batch.correlation_id,
            "hypothesis_id": card.hypothesis_id,
            "approach_ids": approach_ids,
        },
        "experiment": experiment,
        "run": {
            "index": run_index,
            "count": run_count,
            "parameters": parameters,
            "initial_status": run_status.value,
        },
        "approval_policy": approval_policy,
        "resource_policy": approval_policy.get("resource_policy", {}),
        "result_contract": {
            "result_bundle_endpoint": handoff_contract.result_bundle_endpoint(),
            "required_correlation": {
                "experiment_id": card.id,
                "goal_id": card.workspace_id,
                "execution_batch_id": batch.id,
                "correlation_id": batch.correlation_id,
                "hypothesis_id": card.hypothesis_id,
                "approach_ids": approach_ids,
            },
            "expected_metrics": _loads(card.metrics, []),
            "expected_artifacts": _loads(card.artifacts, []),
            "pass_conditions": pass_conditions,
        },
        "control_plane_uri": card.experiment_control_plane,
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

    # A prior handoff that failed can be retried into the same batch; only a
    # fully-submitted experiment is blocked from re-submission (CS-APPROVAL-010).
    is_retry = bool(card.execution_batch_id) and card.handoff_status == "failed"
    if card.execution_batch_id and not is_retry:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment {experiment_id!r} already submitted as batch {card.execution_batch_id!r}",
        )

    preview = experiment_svc.preview_run_requests(db, experiment_id, cap=body.cap)
    total = len(preview.runs)
    card_approach_ids = json.loads(card.approach_ids) if card.approach_ids else []

    if is_retry:
        batch = db.get(ExecutionBatchReference, card.execution_batch_id)
        policy = json.loads(batch.approval_policy) if batch.approval_policy else {}
        approval_id = policy.get("approval_id") or str(uuid.uuid4())
    else:
        approval_id = str(uuid.uuid4())
        policy = _build_approval_policy(card, body, approval_id)
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

    run_status = _run_status_for_mode(body.approval_mode, total, body.approval_threshold)
    method_family = _method_family(db, card_approach_ids)

    submitted: list[SubmittedRunRequest] = []
    run_request_ids: list[str] = []
    try:
        for index, item in enumerate(preview.runs):
            existing = _existing_run_for_params(db, experiment_id, item.parameters)
            if existing is not None:
                # Idempotent retry: reuse the RunRequest already handed off.
                rr_id = existing.run_request_id
            else:
                payload = _run_request_payload(
                    card=card,
                    batch=batch,
                    approval_policy=policy,
                    parameters=item.parameters,
                    run_index=index,
                    run_count=total,
                    run_status=run_status,
                    method_family=method_family,
                )
                rr_id = run_request_submitter(payload)
                execution_svc.register_run_request(
                    db,
                    run_request_id=rr_id,
                    experiment_id=experiment_id,
                    goal_id=goal_id,
                    workspace_id=card.workspace_id,
                    execution_batch_id=batch.id,
                    correlation_id=batch.correlation_id,
                    hypothesis_id=card.hypothesis_id,
                    approach_ids=card_approach_ids,
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
    except Exception as exc:  # noqa: BLE001 — preserve any handoff failure for retry
        # Persist the batch + whatever RunRequests were already handed off so a
        # retry doesn't duplicate them, then record the failed handoff.
        card.execution_batch_id = batch.id
        card.run_request_ids = json.dumps(run_request_ids)
        card.handoff_status = "failed"
        db.flush()
        handoff_svc.record_handoff_request(
            db,
            workspace_id=card.workspace_id,
            experiment_id=experiment_id,
            goal_id=goal_id,
            request_type=HandoffRequestTypeEnum.retry if is_retry else HandoffRequestTypeEnum.submit,
            status=HandoffRequestStatusEnum.failed,
            error=str(exc),
            payload_summary={
                "attempted_run_count": total,
                "handed_off_run_count": len(run_request_ids),
            },
            approval_id=approval_id,
            retryable=True,
            run_request_ids=run_request_ids,
            execution_batch_id=batch.id,
            correlation_id=batch.correlation_id,
        )
        governance_svc.record_execution_event(
            db,
            workspace_id=card.workspace_id,
            action=ExecutionAuditActionEnum.handoff_failed,
            actor=body.approver or governance_svc.HANDOFF_AGENT_NAME,
            experiment_id=experiment_id,
            execution_batch_id=batch.id,
            approval_id=approval_id,
            run_request_ids=run_request_ids,
            detail={"error": str(exc)},
        )
        db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Handoff to the Experimentation System failed: {exc}",
        )

    card.execution_batch_id = batch.id
    card.run_request_ids = json.dumps(run_request_ids)
    card.handoff_status = "submitted"
    db.flush()

    if is_retry:
        handoff_svc.record_handoff_request(
            db,
            workspace_id=card.workspace_id,
            experiment_id=experiment_id,
            goal_id=goal_id,
            request_type=HandoffRequestTypeEnum.retry,
            status=HandoffRequestStatusEnum.acknowledged,
            approval_id=approval_id,
            run_request_ids=run_request_ids,
            execution_batch_id=batch.id,
            correlation_id=batch.correlation_id,
        )
        governance_svc.record_execution_event(
            db,
            workspace_id=card.workspace_id,
            action=ExecutionAuditActionEnum.handoff_retried,
            actor=body.approver or governance_svc.HANDOFF_AGENT_NAME,
            experiment_id=experiment_id,
            execution_batch_id=batch.id,
            approval_id=approval_id,
            run_request_ids=run_request_ids,
        )

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
