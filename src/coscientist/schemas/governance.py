from datetime import datetime

from pydantic import BaseModel


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
