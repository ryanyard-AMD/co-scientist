from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


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
    synthesize: bool = False


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
    is_substantive: bool
    record_kind: str
    source_id: str | None
    source_type: str | None
    created_at: datetime


class EvidenceGroupItem(BaseModel):
    group_key: str
    group_type: str
    count: int
    paper_count: int
    substantive_paper_count: int = 0
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


def _dict_to_str(d: dict) -> str:
    """Flatten a dict that a lenient model emitted where a string was expected.

    Prefers a `name: detail` join over common keys, else the first string
    value, else a compact repr — so a stray object never crashes synthesis.
    """
    name = d.get("name") or d.get("title")
    detail = (
        d.get("description")
        or d.get("detail")
        or d.get("finding")
        or d.get("text")
        or d.get("value")
    )
    if name and detail and name != detail:
        return f"{name}: {detail}"
    for cand in (name, detail):
        if isinstance(cand, str) and cand.strip():
            return cand
    for val in d.values():
        if isinstance(val, str) and val.strip():
            return val
    return str(d)


class ReportedMetric(BaseModel):
    name: str
    value: str
    evidence_ids: list[str] = Field(default_factory=list)


class FailureMode(BaseModel):
    """A failure mode with a coarse severity the synthesis agent assigns.

    Severity feeds the Score-stage risk penalty, so it is graded at synthesis
    time (the only point where an LLM reasons about the failure) rather than
    left null for a later revise pass.
    """

    description: str
    severity: str = "medium"

    @field_validator("severity")
    @classmethod
    def _normalize_severity(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in {"low", "medium", "high"} else "medium"


class AgentSynthesisOutput(BaseModel):
    """Schema the synthesis agent must return for one method family."""

    synthesis_text: str
    key_findings: list[str] = Field(default_factory=list)
    reported_metrics: list[ReportedMetric] = Field(default_factory=list)
    hardware_requirements: list[str] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("failure_modes", mode="before")
    @classmethod
    def _coerce_failure_modes(cls, v):
        # Tolerate a bare list of strings (older prompt shape / lenient models).
        if isinstance(v, list):
            return [{"description": x} if isinstance(x, str) else x for x in v]
        return v

    @field_validator(
        "key_findings", "hardware_requirements", "open_questions", mode="before"
    )
    @classmethod
    def _coerce_str_list(cls, v):
        # Lenient models sometimes emit list-of-dict for these string fields
        # (e.g. {"name": ..., "detail": ...}); flatten each item to a string.
        if isinstance(v, list):
            return [_dict_to_str(x) if isinstance(x, dict) else x for x in v]
        return v


class EvidenceSynthesisResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    scout_run_id: str
    method_family: str
    synthesis_text: str
    key_findings: list[str]
    reported_metrics: list[ReportedMetric]
    hardware_requirements: list[str]
    failure_modes: list[str]
    open_questions: list[str]
    cited_evidence_ids: list[str]
    evidence_count: int
    paper_count: int
    model_used: str
    created_at: datetime


class ScoutResultResponse(BaseModel):
    scout_run_id: str
    goal_id: str
    evidence_count: int
    groups: EvidenceGroupResponse
    summary: ScoutSummaryStats
    syntheses: list[EvidenceSynthesisResponse] = Field(default_factory=list)


class EvidenceListResponse(BaseModel):
    items: list[EvidenceRecordResponse]
    total: int
