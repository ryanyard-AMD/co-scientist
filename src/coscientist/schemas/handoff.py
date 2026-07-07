from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class HandoffRequestTypeEnum(str, Enum):
    submit = "submit"
    retry = "retry"
    cancel = "cancel"
    resubmit = "resubmit"


class HandoffRequestStatusEnum(str, Enum):
    failed = "failed"
    requested = "requested"
    acknowledged = "acknowledged"
    rejected = "rejected"


class HandoffControlBody(BaseModel):
    """Cancel / resubmit request initiated by a reviewer. The co-scientist relays
    it to the Experimentation System and records the resulting status; it does
    not itself stop or start execution."""

    requester: str | None = None
    reason: str | None = None


class HandoffRequestResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    experiment_id: str
    goal_id: str
    request_type: HandoffRequestTypeEnum
    status: HandoffRequestStatusEnum
    error: str | None
    payload_summary: dict | None
    approval_id: str | None
    retryable: bool
    run_request_ids: list[str]
    execution_batch_id: str | None
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime


class HandoffRequestListResponse(BaseModel):
    items: list[HandoffRequestResponse]
    total: int
