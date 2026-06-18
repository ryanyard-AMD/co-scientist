from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from coscientist.schemas.experiment import ExperimentCardResponse


class ApprovalDecisionEnum(str, Enum):
    approve = "approve"
    reject = "reject"
    request_edit = "request_edit"


class ResourceFlagEnum(str, Enum):
    treble = "treble"
    gpu = "gpu"
    shared_compute = "shared_compute"
    credentials = "credentials"
    high_cost = "high_cost"


class ApprovalDecisionCreate(BaseModel):
    decision: ApprovalDecisionEnum
    reviewer_id: str | None = None
    reason: str | None = None
    resource_flags: list[ResourceFlagEnum] = Field(default_factory=list)

    @model_validator(mode="after")
    def reason_required_for_reject_and_request_edit(self) -> "ApprovalDecisionCreate":
        if self.decision in (ApprovalDecisionEnum.reject, ApprovalDecisionEnum.request_edit):
            if not self.reason:
                raise ValueError("reason is required for reject and request_edit decisions")
        return self


class ApprovalActionBody(BaseModel):
    reviewer_id: str | None = None
    reason: str | None = None
    resource_flags: list[ResourceFlagEnum] = Field(default_factory=list)


class ApprovalDecisionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    experiment_id: str
    goal_id: str
    decision: ApprovalDecisionEnum
    reviewer_id: str | None
    reason: str | None
    resource_flags: list[str]
    created_at: datetime


class ApprovalDecisionListResponse(BaseModel):
    items: list[ApprovalDecisionResponse]
    total: int


class ExperimentDuplicateResponse(BaseModel):
    original_id: str
    new_id: str
    new_experiment: ExperimentCardResponse
