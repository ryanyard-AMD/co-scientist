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
