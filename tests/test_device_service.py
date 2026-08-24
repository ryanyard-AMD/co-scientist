import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.device import (
    AgentDeviceConceptItem,
    AcousticArchitecture,
    DeviceConceptGenerateRequest,
    DeviceConceptStatusEnum,
    ExpectedPerformance,
    FormFactor,
    HardwareSpec,
    UseCase,
)
from coscientist.schemas.approach import ApproachGenerateRequest, ApproachStatusEnum
from coscientist.services import approach as approach_svc
from coscientist.services import goal as goal_svc
from coscientist.services import score as score_svc
from coscientist.services import device as svc


MOCK_CONCEPTS = [
    AgentDeviceConceptItem(
        name="Near-field Desktop PSZ Bar",
        description="A compact speaker array for desktop personal sound zones.",
        rationale="Combines beamforming and pressure matching for robust near-field control.",
        maturity="simulated",
        form_factor=FormFactor(type="desktop_bar", placement="under_monitor", listener_distance_cm="50-80"),
        use_case=UseCase(primary="private_desktop_audio", secondary=["speech_privacy"]),
        acoustic_architecture=AcousticArchitecture(
            control_stack=["beamforming", "pressure_matching"],
            calibration=["measured_transfer_functions"],
            simulation_backing=["room_impulse_response"],
        ),
        hardware=HardwareSpec(
            speakers={"estimated_count": 8, "geometry": "linear"},
            microphones={"calibration_count": "2", "runtime_feedback": "optional"},
            compute={"prototype": "laptop", "production_candidate": "embedded_dsp"},
        ),
        expected_performance=ExpectedPerformance(
            bright_zone="15-20 dB contrast",
            dark_zone="<-15 dB",
            latency="<10 ms",
            robustness="medium",
        ),
        unresolved_risks=["low_frequency_leakage", "head_movement_sensitivity"],
        next_steps=["build_simulation_bench", "prototype_8_speaker_array"],
    ),
]


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD))


def _seed_evidence(db, workspace_id, method_family="beamforming"):
    now = datetime.now(timezone.utc)
    for _ in range(2):
        rec = EvidenceRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            scout_run_id="sr-test",
            query_text="test query",
            paper_id=f"paper-{uuid.uuid4().hex[:8]}",
            title="Test Paper",
            chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
            chunk_index=0,
            chunk_text="Acoustic contrast control for personal sound zones.",
            score=0.9,
            method_families=json.dumps([method_family]),
            metric_names=json.dumps([]),
            hardware_assumptions=json.dumps([]),
            failure_modes=json.dumps([]),
            is_primary_method=True,
            evidence_strength="strong",
            created_at=now,
        )
        db.add(rec)
    db.commit()


def _create_validated_approach(db, goal_id, method_family="beamforming"):
    _seed_evidence(db, goal_id, method_family)
    approach_svc.generate_approaches(db, goal_id, ApproachGenerateRequest(method_families=[method_family]))
    approaches, _ = approach_svc.list_approaches(db, goal_id)
    approach = next(a for a in approaches if a.method_family == method_family)
    approach_svc.transition(db, approach.id, ApproachStatusEnum.reviewed)
    score_svc.score_approach(db, approach.id)
    approach_svc.transition(db, approach.id, ApproachStatusEnum.experiment_proposed)
    approach_svc.transition(db, approach.id, ApproachStatusEnum.tested)
    approach_svc.transition(db, approach.id, ApproachStatusEnum.validated)
    return approach


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_generate_creates_device_concepts(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    request = DeviceConceptGenerateRequest()
    result = svc.generate(db_session, goal.id, request)
    assert result.generated == 1
    assert result.items[0].name == "Near-field Desktop PSZ Bar"
    assert result.generation_run_id != ""


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_generate_populates_approach_ids(mock_agent, db_session):
    goal = _create_goal(db_session)
    approach = _create_validated_approach(db_session, goal.id)
    result = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    assert approach.id in result.items[0].approach_ids


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_generate_sets_generation_run_id(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    result = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    assert result.items[0].generation_run_id == result.generation_run_id


def test_generate_goal_not_found_raises_404(db_session):
    with pytest.raises(Exception) as exc_info:
        svc.generate(db_session, "nonexistent-goal", DeviceConceptGenerateRequest())
    assert "404" in str(exc_info.value.status_code) or exc_info.value.status_code == 404


def test_generate_no_approaches_returns_empty(db_session):
    goal = _create_goal(db_session)
    result = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    assert result.generated == 0
    assert result.items == []


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_get_returns_card(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    result = svc.get(db_session, device_id, goal.id)
    assert result.id == device_id
    assert result.name == "Near-field Desktop PSZ Bar"


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_get_wrong_goal_raises_404(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    with pytest.raises(Exception) as exc_info:
        svc.get(db_session, device_id, "wrong-goal")
    assert exc_info.value.status_code == 404


def test_get_nonexistent_raises_404(db_session):
    goal = _create_goal(db_session)
    with pytest.raises(Exception) as exc_info:
        svc.get(db_session, "nonexistent", goal.id)
    assert exc_info.value.status_code == 404


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_list_devices_all(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    result = svc.list_devices(db_session, goal.id)
    assert result.total == 1


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_list_devices_filtered_by_status(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.reviewed)
    generated = svc.list_devices(db_session, goal.id, status=DeviceConceptStatusEnum.generated)
    reviewed = svc.list_devices(db_session, goal.id, status=DeviceConceptStatusEnum.reviewed)
    assert generated.total == 0
    assert reviewed.total == 1


def test_list_devices_empty_goal(db_session):
    goal = _create_goal(db_session)
    result = svc.list_devices(db_session, goal.id)
    assert result.total == 0


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_transition_generated_to_reviewed(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    result = svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.reviewed)
    assert result.status == DeviceConceptStatusEnum.reviewed


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_transition_generated_to_superseded(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    result = svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.superseded)
    assert result.status == DeviceConceptStatusEnum.superseded


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_transition_reviewed_to_superseded(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.reviewed)
    result = svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.superseded)
    assert result.status == DeviceConceptStatusEnum.superseded


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_transition_invalid_raises_422(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    with pytest.raises(Exception) as exc_info:
        svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.generated)
    assert exc_info.value.status_code == 422


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_transition_terminal_state_raises_422(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.superseded)
    with pytest.raises(Exception) as exc_info:
        svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.reviewed)
    assert exc_info.value.status_code == 422


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_delete_generated_succeeds(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    svc.delete(db_session, device_id, goal.id)
    result = svc.list_devices(db_session, goal.id)
    assert result.total == 0


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_delete_reviewed_raises_409(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    svc.transition(db_session, device_id, goal.id, DeviceConceptStatusEnum.reviewed)
    with pytest.raises(Exception) as exc_info:
        svc.delete(db_session, device_id, goal.id)
    assert exc_info.value.status_code == 409


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_compare_returns_comparison(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id, "beamforming")
    _seed_evidence(db_session, goal.id, "pressure_matching")
    approach_svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest(method_families=["pressure_matching"]))
    approaches, _ = approach_svc.list_approaches(db_session, goal.id)
    pm = next(a for a in approaches if a.method_family == "pressure_matching")
    approach_svc.transition(db_session, pm.id, ApproachStatusEnum.reviewed)
    score_svc.score_approach(db_session, pm.id)
    approach_svc.transition(db_session, pm.id, ApproachStatusEnum.experiment_proposed)
    approach_svc.transition(db_session, pm.id, ApproachStatusEnum.tested)
    approach_svc.transition(db_session, pm.id, ApproachStatusEnum.validated)

    mock_agent.return_value = MOCK_CONCEPTS + [
        AgentDeviceConceptItem(
            name="Headrest PSZ Array",
            description="Headrest-integrated personal sound zone.",
            rationale="Uses pressure matching for headrest form factor.",
            maturity="theoretical",
            form_factor=FormFactor(type="headrest", placement="chair_headrest", listener_distance_cm="10-20"),
            use_case=UseCase(primary="private_audio_in_car"),
            acoustic_architecture=AcousticArchitecture(control_stack=["pressure_matching"]),
            hardware=HardwareSpec(
                speakers={"estimated_count": 4, "geometry": "curved"},
                microphones={"calibration_count": "1"},
                compute={"prototype": "raspberry_pi"},
            ),
            expected_performance=ExpectedPerformance(bright_zone="10 dB"),
            unresolved_risks=["room_sensitivity"],
            next_steps=["prototype_curved_array"],
        )
    ]

    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    assert gen.generated == 2
    ids = [c.id for c in gen.items]
    result = svc.compare(db_session, goal.id, ids)
    assert len(result.concepts) == 2
    assert "form_factor_type" in result.dimensions


def test_compare_single_id_raises_400(db_session):
    goal = _create_goal(db_session)
    with pytest.raises(Exception) as exc_info:
        svc.compare(db_session, goal.id, ["single-id"])
    assert exc_info.value.status_code == 400


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_export_markdown_contains_sections(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    result = svc.export_device(db_session, device_id, goal.id, "markdown")
    assert "# Near-field Desktop PSZ Bar" in result.content
    assert "## Form Factor" in result.content
    assert "## Acoustic Architecture" in result.content
    assert "## Hardware" in result.content
    assert "## Unresolved Risks" in result.content
    assert "## Next Steps" in result.content


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
def test_export_json_is_valid(mock_agent, db_session):
    goal = _create_goal(db_session)
    _create_validated_approach(db_session, goal.id)
    gen = svc.generate(db_session, goal.id, DeviceConceptGenerateRequest())
    device_id = gen.items[0].id
    result = svc.export_device(db_session, device_id, goal.id, "json")
    assert result.format == "json"
    data = json.loads(result.content)
    assert data["name"] == "Near-field Desktop PSZ Bar"
    assert "unresolved_risks" in data


# --- device geometry simulation (spec→model bridge) ---

_SIM_RESPONSE = {
    "acoustic_contrast_db": 43.46,
    "per_band": [
        {"freq_hz": 2000.0, "contrast_db": 47.4},
        {"freq_hz": 8000.0, "contrast_db": 37.96},
    ],
    "model_flags": {"t60_s": 0.4, "pal_model": "berktay", "n_elements": 8, "layout": "ula"},
    "resolved_geometry": {"layout": "ula", "n_elements": 8},
    "approximations": ["linear superposition of demodulated PAL audio fields"],
}


_OPT_RESPONSE = {
    "best": {
        "acoustic_contrast_db": 35.77,
        "per_band": [
            {"freq_hz": 2000.0, "contrast_db": 38.0},
            {"freq_hz": 8000.0, "contrast_db": 33.5},
        ],
        "model_flags": {"pal_model": "berktay", "n_elements": 16, "layout": "ula"},
        "resolved_geometry": {"layout": "ula", "n_elements": 16},
        "approximations": ["linear superposition of demodulated PAL audio fields"],
    },
    "best_overrides": {"n_elements": 16},
    "best_contrast_db": 35.77,
    "swept_keys": ["n_elements"],
    "n_candidates": 3,
    "rooms_built": 3,
    "candidates": [
        {"overrides": {"n_elements": 16}, "acoustic_contrast_db": 35.77, "n_elements": 16,
         "per_band": [{"freq_hz": 2000.0, "contrast_db": 38.0}]},
        {"overrides": {"n_elements": 8}, "acoustic_contrast_db": 28.33, "n_elements": 8,
         "per_band": [{"freq_hz": 2000.0, "contrast_db": 30.0}]},
        {"overrides": {"n_elements": 4}, "acoustic_contrast_db": 24.89, "n_elements": 4,
         "per_band": [{"freq_hz": 2000.0, "contrast_db": 26.0}]},
    ],
}


_REPRODUCE_RESPONSE = {
    "mode": "sound_field_reproduction",
    "solver": "pressure_matching",
    "target": {"kind": "plane_wave", "origin": [0.0, -1.0, 0.0], "direction": [0.0, 1.0, 0.0]},
    "normalized_reproduction_error": 0.2175,
    "spatial_correlation": 0.9412,
    "mean_spl_error_db": 1.88,
    "max_spl_error_db": 4.73,
    "array_effort": 2.41,
    "acoustic_contrast_db": 18.6,
    "per_band": [
        {
            "freq_hz": 2000.0,
            "normalized_reproduction_error": 0.2,
            "spatial_correlation": 0.95,
            "mean_spl_error_db": 1.5,
            "max_spl_error_db": 3.9,
            "array_effort": 2.1,
            "acoustic_contrast_db": 20.0,
        }
    ],
    "model_flags": {"t60_s": 0.0, "pal_model": "point_source", "n_elements": 16, "layout": "ula"},
    "resolved_geometry": {"layout": "ula", "n_elements": 16, "control_points": 27, "evaluation_points": 27},
    "approximations": ["frequency-domain pressure matching with Tikhonov regularization"],
}


class _FakeReproClient:
    """Captures the geometry handed to the repro device-sim endpoint."""

    last_geometry: dict | None = None
    last_base: dict | None = None
    last_search_space: dict | None = None
    last_max_candidates: int | None = None
    last_reproduction_request: dict | None = None
    response: dict = _SIM_RESPONSE
    opt_response: dict = _OPT_RESPONSE
    reproduce_response: dict = _REPRODUCE_RESPONSE

    def __init__(self, *args, **kwargs):
        pass

    def simulate_device(self, geometry):
        type(self).last_geometry = geometry
        return self.response

    def reproduce_device(self, request):
        type(self).last_reproduction_request = request
        return self.reproduce_response

    def optimize_device(self, base, search_space, *, max_candidates=24):
        type(self).last_base = base
        type(self).last_search_space = search_space
        type(self).last_max_candidates = max_candidates
        return self.opt_response

    def close(self):
        pass


def _make_device(db):
    goal = _create_goal(db)
    _create_validated_approach(db, goal.id)
    gen = svc.generate(db, goal.id, DeviceConceptGenerateRequest())
    return goal, gen.items[0].id


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_simulate_populates_card(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    result = svc.simulate(db_session, device_id, goal.id)

    assert result.device_id == device_id
    assert result.acoustic_contrast_db == 43.46
    assert result.target_contrast_db == svc.DEFAULT_TARGET_CONTRAST_DB
    assert result.meets_target is True
    assert len(result.per_band) == 2

    # persisted onto the card and surfaced through get()
    card = svc.get(db_session, device_id, goal.id)
    assert card.simulation["acoustic_contrast_db"] == 43.46
    assert card.simulation["meets_target"] is True
    assert "simulated_at" in card.simulation


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_simulate_resolves_geometry_from_card(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    svc.simulate(db_session, device_id, goal.id)

    geo = _FakeReproClient.last_geometry
    # MOCK_CONCEPTS: speakers estimated_count=8, geometry "linear" → ula;
    # listener_distance_cm "50-80" → 0.5 m boresight.
    assert geo["layout"] == "ula"
    assert geo["n_elements"] == 8
    assert geo["listener"] == [0.0, 0.5, 0.0]
    assert geo["pal_model"] is True


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_simulate_below_target(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    _FakeReproClient.response = {**_SIM_RESPONSE, "acoustic_contrast_db": 9.1}
    try:
        result = svc.simulate(db_session, device_id, goal.id)
        assert result.meets_target is False
    finally:
        _FakeReproClient.response = _SIM_RESPONSE


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_simulate_honors_execution_boundary(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    with patch("coscientist.services.governance.settings.enforce_execution_boundary", True):
        with pytest.raises(Exception) as exc_info:
            svc.simulate(db_session, device_id, goal.id)
    assert exc_info.value.status_code == 403


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_simulate_applies_overrides(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    result = svc.simulate(
        db_session, device_id, goal.id,
        overrides={"n_elements": 16, "aperture": 0.008},
    )
    geo = _FakeReproClient.last_geometry
    # overrides win over the card-resolved defaults (n_elements resolved to 8)
    assert geo["n_elements"] == 16
    assert geo["aperture"] == 0.008
    assert geo["layout"] == "ula"          # untouched knob still resolved from card
    assert result.overrides == {"n_elements": 16, "aperture": 0.008}
    # recorded on the card for refine-loop transparency
    card = svc.get(db_session, device_id, goal.id)
    assert card.simulation["overrides"] == {"n_elements": 16, "aperture": 0.008}


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_simulate_rejects_unknown_override(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    with pytest.raises(ValueError, match="unknown geometry override"):
        svc.simulate(db_session, device_id, goal.id, overrides={"bogus_knob": 3})


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_simulate_reports_previous_contrast_delta(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    first = svc.simulate(db_session, device_id, goal.id)
    assert first.previous_contrast_db is None      # nothing persisted yet

    _FakeReproClient.response = {**_SIM_RESPONSE, "acoustic_contrast_db": 30.0}
    try:
        second = svc.simulate(
            db_session, device_id, goal.id, overrides={"n_elements": 16}
        )
    finally:
        _FakeReproClient.response = _SIM_RESPONSE
    # the re-run sees the prior prediction so the CLI can show the delta
    assert second.previous_contrast_db == 43.46
    assert second.acoustic_contrast_db == 30.0


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_reproduce_populates_card_with_quality_metrics(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    result = svc.reproduce(
        db_session,
        device_id,
        goal.id,
        target_kind="plane_wave",
        regularization=0.01,
        control_grid_n=3,
        eval_grid_n=3,
        overrides={"n_elements": 16, "t60": 0.0},
    )

    assert result.device_id == device_id
    assert result.mode == "sound_field_reproduction"
    assert result.normalized_reproduction_error == 0.2175
    assert result.spatial_correlation == 0.9412
    assert result.per_band[0].acoustic_contrast_db == 20.0

    req = _FakeReproClient.last_reproduction_request
    assert req["layout"] == "ula"
    assert req["n_elements"] == 16
    assert req["t60"] == 0.0
    assert req["target_kind"] == "plane_wave"
    assert req["regularization"] == 0.01
    assert req["control_grid_n"] == 3
    assert req["eval_grid_n"] == 3

    card = svc.get(db_session, device_id, goal.id)
    assert card.simulation["mode"] == "sound_field_reproduction"
    assert card.simulation["normalized_reproduction_error"] == 0.2175
    assert card.simulation["spatial_correlation"] == 0.9412
    assert card.simulation["overrides"] == {"n_elements": 16, "t60": 0.0}


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_reproduce_reports_previous_reproduction_error(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    first = svc.reproduce(db_session, device_id, goal.id)
    assert first.previous_normalized_reproduction_error is None

    _FakeReproClient.reproduce_response = {
        **_REPRODUCE_RESPONSE,
        "normalized_reproduction_error": 0.12,
    }
    try:
        second = svc.reproduce(db_session, device_id, goal.id)
    finally:
        _FakeReproClient.reproduce_response = _REPRODUCE_RESPONSE
    assert second.previous_normalized_reproduction_error == 0.2175
    assert second.normalized_reproduction_error == 0.12


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_reproduce_honors_execution_boundary(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    with patch("coscientist.services.governance.settings.enforce_execution_boundary", True):
        with pytest.raises(Exception) as exc_info:
            svc.reproduce(db_session, device_id, goal.id)
    assert exc_info.value.status_code == 403


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_optimize_picks_best_and_persists(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    result = svc.optimize(
        db_session, device_id, goal.id, {"n_elements": [4, 8, 16]}
    )

    assert result.best_contrast_db == 35.77
    assert result.best_overrides == {"n_elements": 16}
    assert result.meets_target is True
    assert result.n_candidates == 3
    assert result.swept_keys == ["n_elements"]
    assert len(result.candidates) == 3
    assert result.candidates[0].acoustic_contrast_db == 35.77

    # base resolved from the card, search space forwarded to repro
    assert _FakeReproClient.last_search_space == {"n_elements": [4, 8, 16]}
    assert _FakeReproClient.last_base["layout"] == "ula"

    # winning prediction persisted onto the card like simulate()
    card = svc.get(db_session, device_id, goal.id)
    assert card.simulation["acoustic_contrast_db"] == 35.77
    assert card.simulation["overrides"] == {"n_elements": 16}
    assert card.simulation["optimization"]["swept_keys"] == ["n_elements"]


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_optimize_rejects_unknown_knob(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    with pytest.raises(ValueError, match="unknown geometry override"):
        svc.optimize(db_session, device_id, goal.id, {"bogus_knob": [1, 2]})


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_optimize_rejects_empty_search_space(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    with pytest.raises(ValueError, match="search_space is empty"):
        svc.optimize(db_session, device_id, goal.id, {})


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_optimize_reports_previous_contrast(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    svc.simulate(db_session, device_id, goal.id)      # seeds a prior prediction (43.46)
    result = svc.optimize(db_session, device_id, goal.id, {"n_elements": [4, 8, 16]})
    assert result.previous_contrast_db == 43.46


@patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS)
@patch("coscientist.services.device.ReproClient", _FakeReproClient)
def test_optimize_honors_execution_boundary(mock_agent, db_session):
    goal, device_id = _make_device(db_session)
    with patch("coscientist.services.governance.settings.enforce_execution_boundary", True):
        with pytest.raises(Exception) as exc_info:
            svc.optimize(db_session, device_id, goal.id, {"n_elements": [4, 8]})
    assert exc_info.value.status_code == 403
