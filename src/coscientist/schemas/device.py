from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DeviceConceptStatusEnum(str, Enum):
    generated = "generated"
    reviewed = "reviewed"
    superseded = "superseded"


class DeviceMaturityEnum(str, Enum):
    theoretical = "theoretical"
    simulated = "simulated"
    measured = "measured"
    validated = "validated"


# --- Sub-schemas for JSON fields ---

class FormFactor(BaseModel):
    type: str = ""
    placement: str = ""
    listener_distance_cm: str = ""

    model_config = {"extra": "allow"}


class UseCase(BaseModel):
    primary: str = ""
    secondary: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class AcousticArchitecture(BaseModel):
    control_stack: list[str] = Field(default_factory=list)
    calibration: list[str] = Field(default_factory=list)
    simulation_backing: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class HardwareSpec(BaseModel):
    speakers: dict = Field(default_factory=dict)
    microphones: dict = Field(default_factory=dict)
    compute: dict = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class ExpectedPerformance(BaseModel):
    bright_zone: str = ""
    dark_zone: str = ""
    latency: str = ""
    robustness: str = ""

    model_config = {"extra": "allow"}


# --- Agent internal schema ---

class AgentDeviceConceptItem(BaseModel):
    name: str
    description: str = ""
    rationale: str = ""
    maturity: str = "theoretical"
    form_factor: FormFactor = Field(default_factory=FormFactor)
    use_case: UseCase = Field(default_factory=UseCase)
    acoustic_architecture: AcousticArchitecture = Field(default_factory=AcousticArchitecture)
    hardware: HardwareSpec = Field(default_factory=HardwareSpec)
    expected_performance: ExpectedPerformance = Field(default_factory=ExpectedPerformance)
    unresolved_risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


# --- Request schemas ---

class DeviceConceptGenerateRequest(BaseModel):
    approach_ids: list[str] = Field(default_factory=list)


class DeviceConceptTransitionRequest(BaseModel):
    status: DeviceConceptStatusEnum


# --- Response schemas ---

class DeviceConceptCardResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str | None
    status: DeviceConceptStatusEnum
    maturity: DeviceMaturityEnum
    confidence: float
    form_factor: FormFactor
    use_case: UseCase
    acoustic_architecture: AcousticArchitecture
    hardware: HardwareSpec
    expected_performance: ExpectedPerformance
    approach_ids: list[str]
    experiment_ids: list[str]
    validation_result_ids: list[str]
    unresolved_risks: list[str]
    next_steps: list[str]
    rationale: str | None
    model_used: str | None
    generation_run_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeviceConceptCardListResponse(BaseModel):
    items: list[DeviceConceptCardResponse]
    total: int


class DeviceConceptGenerateResponse(BaseModel):
    generated: int
    generation_run_id: str
    items: list[DeviceConceptCardResponse]


class DeviceConceptExportResponse(BaseModel):
    device_id: str
    format: str
    content: str


class DeviceConceptComparisonItem(BaseModel):
    id: str
    name: str
    values: dict[str, str]


class DeviceConceptComparisonResponse(BaseModel):
    dimensions: list[str]
    concepts: list[DeviceConceptComparisonItem]


# --- Execution evidence (CS-EPIC-DEVICE) ---

class DeviceExperimentEvidence(BaseModel):
    experiment_id: str
    experiment_name: str
    validation_status: str | None = None
    passed_runs: int = 0
    failed_runs: int = 0
    total_runs: int = 0
    execution_batch_id: str | None = None
    result_bundle_ids: list[str] = Field(default_factory=list)
    passing_metrics: dict = Field(default_factory=dict)
    failed_assumptions: list[str] = Field(default_factory=list)


class DeviceExecutionEvidenceResponse(BaseModel):
    device_id: str
    device_name: str
    status: DeviceConceptStatusEnum
    confidence: float
    passed_experiments: int
    failed_experiments: int
    inconclusive_experiments: int
    unresolved_risks: list[str] = Field(default_factory=list)
    experiments: list[DeviceExperimentEvidence] = Field(default_factory=list)
    affected_approach_scores: dict = Field(default_factory=dict)


class DeviceEvidenceUpdateResponse(BaseModel):
    id: str
    device_id: str
    workspace_id: str
    validation_status: str
    previous_confidence: float
    new_confidence: float
    confidence_delta: float
    passed_experiments: int
    failed_experiments: int
    inconclusive_experiments: int
    supporting_result_bundle_refs: list[str]
    affected_approach_ids: list[str]
    score_deltas: dict
    added_risks: list[str]
    rationale: str
    created_at: datetime


class DeviceEvidenceUpdateListResponse(BaseModel):
    items: list[DeviceEvidenceUpdateResponse]
    total: int
