from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class FeedbackTargetEnum(str, Enum):
    approach = "approach"
    score = "score"
    experiment = "experiment"
    device = "device"
    hypothesis = "hypothesis"
    roadmap = "roadmap"


class FeedbackCreate(BaseModel):
    target_type: FeedbackTargetEnum
    target_id: str
    is_positive: bool
    comment: str | None = None
    reviewer_id: str | None = None


class FeedbackResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    target_type: FeedbackTargetEnum
    target_id: str
    is_positive: bool
    comment: str | None
    reviewer_id: str | None
    created_at: datetime


class FeedbackListResponse(BaseModel):
    items: list[FeedbackResponse]
    total: int
