from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OntologyCategoryEnum(str, Enum):
    method = "method"
    metric = "metric"
    hardware = "hardware"
    failure_mode = "failure_mode"
    acoustic_goal = "acoustic_goal"
    scene_assumption = "scene_assumption"


class RelationshipTypeEnum(str, Enum):
    related_to = "related_to"
    subsumes = "subsumes"
    alias_of = "alias_of"


class TermCreate(BaseModel):
    canonical_name: str
    category: OntologyCategoryEnum
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)


class TermUpdate(BaseModel):
    canonical_name: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    status: str | None = None


class TermMergeRequest(BaseModel):
    source_term_id: str
    target_term_id: str


class TermResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    canonical_name: str
    category: OntologyCategoryEnum
    description: str | None
    keywords: list[str]
    status: str
    created_at: datetime
    updated_at: datetime


class TermListResponse(BaseModel):
    items: list[TermResponse]
    total: int


class RelationshipCreate(BaseModel):
    source_term_id: str
    target_term_id: str
    relationship_type: RelationshipTypeEnum


class RelationshipResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    source_term_id: str
    target_term_id: str
    relationship_type: RelationshipTypeEnum
    created_at: datetime
