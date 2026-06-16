from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EvidenceStrengthEnum(str, Enum):
    strong = "strong"
    weak = "weak"
    none_ = "none"


class ScoutFilterRequest(BaseModel):
    year_min: int | None = None
    year_max: int | None = None
    authors: list[str] | None = None
    source_collection: str | None = None
    source_tag: str | None = None
    method_families: list[str] | None = None
    metric_names: list[str] | None = None


class ScoutRunRequest(BaseModel):
    method_families: list[str] | None = None
    top_k: int = Field(default=20, ge=1, le=100)
    filters: ScoutFilterRequest | None = None


class EvidenceRecordResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    scout_run_id: str
    query_text: str
    paper_id: str
    title: str
    year: int | None
    section_title: str | None
    page_number: int | None
    chunk_id: str
    chunk_index: int
    chunk_text: str
    score: float
    vector_score: float | None
    fulltext_score: float | None
    method_families: list[str]
    metric_names: list[str]
    hardware_assumptions: list[str]
    failure_modes: list[str]
    is_primary_method: bool
    claim_type: str | None
    confidence: float | None
    evidence_strength: EvidenceStrengthEnum
    source_id: str | None
    source_type: str | None
    created_at: datetime


class EvidenceGroupItem(BaseModel):
    group_key: str
    group_type: str
    count: int
    paper_count: int
    avg_score: float
    evidence_strength: EvidenceStrengthEnum
    evidence_ids: list[str]


class EvidenceGroupResponse(BaseModel):
    groups: list[EvidenceGroupItem]
    total_groups: int
    total_evidence: int


class SparsityWarning(BaseModel):
    query_or_category: str
    category_type: str
    papers_found: int
    evidence_strength: EvidenceStrengthEnum
    suggested_related: list[str]


class ScoutSummaryStats(BaseModel):
    scout_run_id: str
    goal_id: str
    total_evidence: int
    total_papers: int
    total_queries: int
    queries_executed: list[str]
    method_families_found: list[str]
    strong_evidence_count: int
    weak_evidence_count: int
    no_evidence_count: int
    warnings: list[SparsityWarning]


class ScoutResultResponse(BaseModel):
    scout_run_id: str
    goal_id: str
    evidence_count: int
    groups: EvidenceGroupResponse
    summary: ScoutSummaryStats


class EvidenceListResponse(BaseModel):
    items: list[EvidenceRecordResponse]
    total: int
