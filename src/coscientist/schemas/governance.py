from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ExecutionAuditActionEnum(str, Enum):
    handoff_submitted = "handoff_submitted"
    run_status_updated = "run_status_updated"
    result_bundle_ingested = "result_bundle_ingested"


class EvidenceLabelResponse(BaseModel):
    """CS-GOV-012: evidence label for an experiment so speculative plans are not
    mistaken for validated results."""

    experiment_id: str
    label: str
    lifecycle_status: str
    execution_status: str
    validation_status: str | None


class ExecutionAuditLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    action: ExecutionAuditActionEnum
    actor: str | None
    experiment_id: str | None
    execution_batch_id: str | None
    approval_id: str | None
    run_request_ids: list[str]
    policy: dict | None
    payload_checksum: str | None
    detail: dict | None
    created_at: datetime


class ExecutionAuditLogListResponse(BaseModel):
    items: list[ExecutionAuditLogResponse]
    total: int


class AgentActionLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    service: str
    action: str
    model_used: str
    prompt_tokens: int | None
    completion_tokens: int | None
    elapsed_ms: int | None
    response_summary: str | None
    error: str | None
    created_at: datetime


class AgentActionLogListResponse(BaseModel):
    items: list[AgentActionLogResponse]
    total: int
