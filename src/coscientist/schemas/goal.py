import re
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class GoalStatusEnum(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


_OPERATOR_RE = re.compile(r"^(>=|<=|==|>|<)$")


class SuccessCriterion(BaseModel):
    name: str
    operator: str
    target: float
    unit: str

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, v: str) -> str:
        if not _OPERATOR_RE.match(v):
            raise ValueError(f"operator must be one of >=, <=, ==, >, < — got {v!r}")
        return v


class DeviceConstraints(BaseModel):
    speaker_count: int | None = None
    form_factor: str | None = None
    compute_budget: str | None = None
    setup_time_minutes: int | None = None


class GoalCreate(BaseModel):
    name: str
    description: str | None = None
    target_application: str
    success_criteria: list[SuccessCriterion]
    device_constraints: DeviceConstraints | None = None
    is_restricted: bool = False
    pinned_method_families: list[str] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_application: str | None = None
    success_criteria: list[SuccessCriterion] | None = None
    device_constraints: DeviceConstraints | None = None
    is_restricted: bool | None = None
    pinned_method_families: list[str] | None = None


class GoalStatusUpdate(BaseModel):
    status: GoalStatusEnum


class GoalResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: str | None
    target_application: str
    success_criteria: list[SuccessCriterion]
    device_constraints: DeviceConstraints | None
    status: GoalStatusEnum
    is_restricted: bool
    pinned_method_families: list[str] = Field(default_factory=list)
    workspace_id: str
    created_at: datetime
    updated_at: datetime


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
    total: int
