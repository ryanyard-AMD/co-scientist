import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.experiment import ExperimentCard
from coscientist.models.governance import AgentActionLog, ExecutionAuditLog
from coscientist.models.validation import ValidationAggregation
from coscientist.schemas.governance import (
    AgentActionLogListResponse,
    AgentActionLogResponse,
    EvidenceLabelResponse,
    ExecutionAuditActionEnum,
    ExecutionAuditLogListResponse,
    ExecutionAuditLogResponse,
)

# CS-GOV-007: the co-scientist agent that touches execution is a *handoff* agent.
# It submits RunRequests, monitors status, and ingests results. It never starts
# containers, runs commands, allocates GPUs, or operates solvers directly.
HANDOFF_AGENT_NAME = "Simulation Handoff Agent"


def _to_response(log: AgentActionLog) -> AgentActionLogResponse:
    return AgentActionLogResponse(
        id=log.id,
        workspace_id=log.workspace_id,
        service=log.service,
        action=log.action,
        model_used=log.model_used,
        prompt_tokens=log.prompt_tokens,
        completion_tokens=log.completion_tokens,
        elapsed_ms=log.elapsed_ms,
        response_summary=log.response_summary,
        error=log.error,
        created_at=log.created_at,
    )


def log_agent_call(
    db: Session,
    workspace_id: str,
    service: str,
    action: str,
    model_used: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    elapsed_ms: int | None = None,
    response_summary: str | None = None,
    error: str | None = None,
) -> None:
    try:
        row = AgentActionLog(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            service=service,
            action=action,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=elapsed_ms,
            response_summary=response_summary,
            error=error,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()
    except Exception as exc:
        print(f"[governance] Failed to write agent action log: {exc}", file=sys.stderr)


def list_logs(
    db: Session,
    goal_id: str,
    service: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> AgentActionLogListResponse:
    stmt = (
        select(AgentActionLog)
        .where(AgentActionLog.workspace_id == goal_id)
        .order_by(AgentActionLog.created_at.desc())
    )
    if service is not None:
        stmt = stmt.where(AgentActionLog.service == service)

    all_logs = list(db.scalars(stmt))
    total = len(all_logs)
    page = all_logs[skip : skip + limit]
    return AgentActionLogListResponse(items=[_to_response(l) for l in page], total=total)


def get_log(db: Session, log_id: str, goal_id: str) -> AgentActionLogResponse:
    log = db.get(AgentActionLog, log_id)
    if log is None or log.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Agent action log {log_id!r} not found")
    return _to_response(log)


# ---------------------------------------------------------------------------
# CS-GOV-012: evidence labels
# ---------------------------------------------------------------------------

# Validation aggregation outcome is the most authoritative evidence and wins.
_VALIDATION_LABEL = {
    "passed": "validation-passed",
    "failed": "validation-failed",
    "mixed": "mixed",
    "inconclusive": "inconclusive",
    "partial": "inconclusive",
}
# Otherwise the execution lifecycle drives the label.
_EXECUTION_LABEL = {
    "completed": "completed",
    "failed": "failed",
    "running": "queued",
    "queued": "queued",
    "submitted": "queued",
    "submitting": "queued",
}


def derive_evidence_label(
    lifecycle_status: str,
    execution_status: str,
    validation_status: str | None = None,
) -> str:
    """Label an experiment's evidence state so a speculative plan is never shown
    as a validated result. Precedence: validation outcome > execution lifecycle >
    approval lifecycle. Returns one of proposed, approved, queued, completed,
    failed, validation-passed, validation-failed, mixed, inconclusive."""
    if validation_status and validation_status in _VALIDATION_LABEL:
        return _VALIDATION_LABEL[validation_status]
    if execution_status and execution_status in _EXECUTION_LABEL:
        return _EXECUTION_LABEL[execution_status]
    if lifecycle_status in {"approved", "running", "completed"}:
        return "approved"
    return "proposed"


def experiment_evidence_label(db: Session, experiment_id: str) -> EvidenceLabelResponse:
    card = db.get(ExperimentCard, experiment_id)
    if card is None:
        raise HTTPException(
            status_code=404, detail=f"Experiment card {experiment_id!r} not found"
        )
    agg = db.scalar(
        select(ValidationAggregation).where(
            ValidationAggregation.experiment_id == experiment_id
        )
    )
    validation_status = agg.aggregate_status if agg is not None else None
    return EvidenceLabelResponse(
        experiment_id=experiment_id,
        label=derive_evidence_label(card.status, card.execution_status, validation_status),
        lifecycle_status=card.status,
        execution_status=card.execution_status,
        validation_status=validation_status,
    )


# ---------------------------------------------------------------------------
# CS-GOV-011: redaction of runner internals
# ---------------------------------------------------------------------------

REDACTED = "***redacted***"
_PATH_REDACTED = "***path-redacted***"

# Keys whose values are secrets — never surfaced regardless of authorization.
_SECRET_KEY_HINTS = (
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "authorization",
)
# Keys that expose runner internals / operator-only diagnostics — surfaced only
# to an authorized (operator) viewer.
_INTERNAL_KEY_HINTS = (
    "raw_log",
    "runner_log",
    "logs",
    "diagnostic",
    "stack_trace",
    "stacktrace",
    "traceback",
    "operator",
    "node_name",
    "hostname",
)
_LOCAL_PATH_PREFIXES = ("/home/", "/root/", "/var/", "/tmp/", "/mnt/", "/opt/", "/etc/")


def _looks_like_local_path(value: str) -> bool:
    if value.startswith(_LOCAL_PATH_PREFIXES):
        return True
    # Windows drive path e.g. C:\Users\...
    return len(value) > 3 and value[1:3] == ":\\"


def _key_matches(key: str, hints: tuple[str, ...]) -> bool:
    k = key.lower()
    return any(h in k for h in hints)


def redact_runner_internals(value, *, authorized: bool = False):
    """Redact secrets, local filesystem paths, credential names, raw runner logs,
    and operator-only diagnostics from data bound for the UI/API (CS-GOV-011).

    Secrets are always redacted. Runner internals and local paths are redacted
    unless ``authorized`` (an operator view). Returns a redacted copy; the input
    is not mutated.
    """
    if isinstance(value, dict):
        out: dict = {}
        for k, v in value.items():
            if _key_matches(k, _SECRET_KEY_HINTS):
                out[k] = REDACTED
            elif not authorized and _key_matches(k, _INTERNAL_KEY_HINTS):
                out[k] = REDACTED
            else:
                out[k] = redact_runner_internals(v, authorized=authorized)
        return out
    if isinstance(value, list):
        return [redact_runner_internals(v, authorized=authorized) for v in value]
    if isinstance(value, str) and not authorized and _looks_like_local_path(value):
        return _PATH_REDACTED
    return value


# ---------------------------------------------------------------------------
# CS-GOV-008: execution boundary
# ---------------------------------------------------------------------------

def assert_execution_boundary(action: str) -> None:
    """Refuse direct experiment execution when the boundary is enforced.

    The co-scientist is a planning/approval/interpretation layer. Compute and
    credentials are governed by the external Experimentation System, so direct
    execution paths (e.g. the repro runner) are blocked when
    ``enforce_execution_boundary`` is set; experiments run only via RunRequest
    handoff.
    """
    if settings.enforce_execution_boundary:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Execution boundary enforced: the co-scientist cannot {action} directly. "
                "Submit the approved experiment as a RunRequest to the Experimentation System."
            ),
        )


# ---------------------------------------------------------------------------
# CS-GOV-009: execution audit trail
# ---------------------------------------------------------------------------

def payload_checksum(payload: dict) -> str:
    """Stable SHA-256 over a handoff/ingestion payload for accountability."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit_to_response(row: ExecutionAuditLog) -> ExecutionAuditLogResponse:
    return ExecutionAuditLogResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        action=ExecutionAuditActionEnum(row.action),
        actor=row.actor,
        experiment_id=row.experiment_id,
        execution_batch_id=row.execution_batch_id,
        approval_id=row.approval_id,
        run_request_ids=json.loads(row.run_request_ids) if row.run_request_ids else [],
        policy=json.loads(row.policy) if row.policy else None,
        payload_checksum=row.payload_checksum,
        detail=json.loads(row.detail) if row.detail else None,
        created_at=row.created_at,
    )


def record_execution_event(
    db: Session,
    *,
    workspace_id: str,
    action: ExecutionAuditActionEnum,
    actor: str | None = None,
    experiment_id: str | None = None,
    execution_batch_id: str | None = None,
    approval_id: str | None = None,
    run_request_ids: list[str] | None = None,
    policy: dict | None = None,
    payload_checksum: str | None = None,
    detail: dict | None = None,
) -> None:
    """Append an execution-related action to the audit trail (best-effort).

    Flushed, not committed, so it enrolls in the caller's transaction. A logging
    failure must never break the execution handoff it records.
    """
    try:
        row = ExecutionAuditLog(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            action=action.value,
            actor=actor,
            experiment_id=experiment_id,
            execution_batch_id=execution_batch_id,
            approval_id=approval_id,
            run_request_ids=json.dumps(run_request_ids or []),
            policy=json.dumps(policy) if policy is not None else None,
            payload_checksum=payload_checksum,
            detail=json.dumps(detail, default=str) if detail is not None else None,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()
    except Exception as exc:
        print(f"[governance] Failed to write execution audit log: {exc}", file=sys.stderr)


def list_execution_audit(
    db: Session,
    goal_id: str,
    *,
    experiment_id: str | None = None,
    action: ExecutionAuditActionEnum | None = None,
    skip: int = 0,
    limit: int = 50,
) -> ExecutionAuditLogListResponse:
    stmt = (
        select(ExecutionAuditLog)
        .where(ExecutionAuditLog.workspace_id == goal_id)
        .order_by(ExecutionAuditLog.created_at.desc())
    )
    if experiment_id is not None:
        stmt = stmt.where(ExecutionAuditLog.experiment_id == experiment_id)
    if action is not None:
        stmt = stmt.where(ExecutionAuditLog.action == action.value)

    all_rows = list(db.scalars(stmt))
    total = len(all_rows)
    page = all_rows[skip : skip + limit]
    return ExecutionAuditLogListResponse(
        items=[_audit_to_response(r) for r in page], total=total
    )
