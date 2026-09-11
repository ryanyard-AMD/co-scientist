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


# --- Sim-ready geometry block ---

# Geometry knobs the device agent may author, mirroring repro's
# DeviceGeometryRequest. `positions`/`normals` are deliberately excluded: an LLM
# authoring 32x3 float lists burns output tokens against the max_tokens
# truncation guard and says nothing a layout doesn't. They stay reachable
# through simulate-time overrides.
GEOMETRY_SIM_KEYS = frozenset({
    "layout", "n_elements", "cap_radius", "cap_deg", "ring_radius", "pitch",
    "listener", "dark", "zone_half_extent",
    "freqs", "room_dims", "t60", "array_origin",
    "pal_model", "carrier", "aperture", "sidelobe_floor", "nearfield_length",
})


class GeometryClamp(BaseModel):
    """One knob the simulator envelope moved, recorded so an edit is visible
    rather than silent."""

    key: str
    proposed: object = None
    applied: object = None
    bound: str = ""
    reason: str = ""


class DeviceGeometry(BaseModel):
    """Sim-ready geometry knobs (metres, boresight +y) proposed by the device
    agent. Every knob is optional: None means 'fall through to the resolved
    default', so a partial block is valid."""

    layout: str | None = None
    n_elements: int | None = None
    cap_radius: float | None = None
    cap_deg: float | None = None
    ring_radius: float | None = None
    pitch: float | None = None
    listener: list[float] | None = None
    dark: list[float] | None = None
    zone_half_extent: float | None = None
    freqs: list[float] | None = None
    room_dims: list[float] | None = None
    t60: float | None = None
    array_origin: list[float] | None = None
    pal_model: bool | None = None
    carrier: float | None = None
    aperture: float | None = None
    sidelobe_floor: float | None = None
    nearfield_length: float | None = None

    design_intent: str = ""
    clamped: list[GeometryClamp] = Field(default_factory=list)

    # Unlike the prose sub-schemas above, extras are dropped: this block is a
    # wire contract with repro, so an invented key must not reach the payload.
    model_config = {"extra": "ignore"}

    def sim_fields(self) -> dict:
        """Only knobs repro understands, only the ones actually set."""
        return {
            k: v
            for k, v in self.model_dump().items()
            if k in GEOMETRY_SIM_KEYS and v is not None
        }


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
    geometry: DeviceGeometry = Field(default_factory=DeviceGeometry)
    unresolved_risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


# --- Request schemas ---

class DeviceConceptGenerateRequest(BaseModel):
    approach_ids: list[str] = Field(default_factory=list)


class DeviceConceptTransitionRequest(BaseModel):
    status: DeviceConceptStatusEnum


class DeviceGeometrySetRequest(BaseModel):
    """Hand-tune a card's geometry so the refinement survives the next simulate.
    Values are raw knob names; unknown keys are rejected rather than ignored."""

    values: dict
    # Default merges onto the existing block, so a one-knob tweak doesn't wipe the rest.
    replace: bool = False


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
    geometry: DeviceGeometry = Field(default_factory=DeviceGeometry)
    approach_ids: list[str]
    experiment_ids: list[str]
    validation_result_ids: list[str]
    unresolved_risks: list[str]
    next_steps: list[str]
    rationale: str | None
    model_used: str | None
    generation_run_id: str | None
    simulation: dict = Field(default_factory=dict)
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


# --- Device geometry simulation (spec→model bridge) ---

class SimulationPerBand(BaseModel):
    freq_hz: float
    contrast_db: float


class ReproductionPerBand(BaseModel):
    freq_hz: float
    normalized_reproduction_error: float
    spatial_correlation: float
    mean_spl_error_db: float
    max_spl_error_db: float
    array_effort: float
    acoustic_contrast_db: float


class DeviceSimulationResult(BaseModel):
    device_id: str
    simulated_at: datetime
    acoustic_contrast_db: float
    per_band: list[SimulationPerBand] = Field(default_factory=list)
    target_contrast_db: float | None = None
    meets_target: bool | None = None
    resolved_geometry: dict = Field(default_factory=dict)
    model_flags: dict = Field(default_factory=dict)
    approximations: list[str] = Field(default_factory=list)
    repro_endpoint: str
    overrides: dict = Field(default_factory=dict)
    previous_contrast_db: float | None = None
    # Envelope edits the card's stored geometry carries, echoed here so a refine
    # loop sees them at the moment it matters rather than only on `device show`.
    clamped: list[GeometryClamp] = Field(default_factory=list)


class DeviceReproductionResult(BaseModel):
    device_id: str
    simulated_at: datetime
    mode: str = "sound_field_reproduction"
    solver: str
    target: dict = Field(default_factory=dict)
    normalized_reproduction_error: float
    spatial_correlation: float
    mean_spl_error_db: float
    max_spl_error_db: float
    array_effort: float
    acoustic_contrast_db: float
    per_band: list[ReproductionPerBand] = Field(default_factory=list)
    resolved_geometry: dict = Field(default_factory=dict)
    model_flags: dict = Field(default_factory=dict)
    approximations: list[str] = Field(default_factory=list)
    repro_endpoint: str
    overrides: dict = Field(default_factory=dict)
    previous_normalized_reproduction_error: float | None = None


class DeviceReproductionSweepCandidate(BaseModel):
    overrides: dict = Field(default_factory=dict)
    normalized_reproduction_error: float
    spatial_correlation: float
    mean_spl_error_db: float
    max_spl_error_db: float
    array_effort: float
    acoustic_contrast_db: float
    per_band: list[ReproductionPerBand] = Field(default_factory=list)


class DeviceReproductionSweepResult(BaseModel):
    device_id: str
    simulated_at: datetime
    mode: str = "sound_field_reproduction"
    solver: str
    target: dict = Field(default_factory=dict)
    best_overrides: dict = Field(default_factory=dict)
    normalized_reproduction_error: float
    spatial_correlation: float
    mean_spl_error_db: float
    max_spl_error_db: float
    array_effort: float
    acoustic_contrast_db: float
    swept_keys: list[str] = Field(default_factory=list)
    n_candidates: int = 0
    candidates: list[DeviceReproductionSweepCandidate] = Field(default_factory=list)
    resolved_geometry: dict = Field(default_factory=dict)
    model_flags: dict = Field(default_factory=dict)
    repro_endpoint: str
    previous_normalized_reproduction_error: float | None = None


class DeviceOptimizeCandidate(BaseModel):
    overrides: dict = Field(default_factory=dict)
    acoustic_contrast_db: float
    n_elements: int
    per_band: list[SimulationPerBand] = Field(default_factory=list)


class DeviceOptimizeResult(BaseModel):
    device_id: str
    simulated_at: datetime
    best_contrast_db: float
    best_overrides: dict = Field(default_factory=dict)
    target_contrast_db: float | None = None
    meets_target: bool | None = None
    swept_keys: list[str] = Field(default_factory=list)
    n_candidates: int = 0
    rooms_built: int = 0
    candidates: list[DeviceOptimizeCandidate] = Field(default_factory=list)
    resolved_geometry: dict = Field(default_factory=dict)
    model_flags: dict = Field(default_factory=dict)
    repro_endpoint: str
    previous_contrast_db: float | None = None


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
