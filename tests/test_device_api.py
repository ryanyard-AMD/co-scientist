import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.device import (
    AgentDeviceConceptItem,
    AcousticArchitecture,
    DeviceConceptStatusEnum,
    ExpectedPerformance,
    FormFactor,
    HardwareSpec,
    UseCase,
)

MOCK_CONCEPTS = [
    AgentDeviceConceptItem(
        name="Near-field Desktop PSZ Bar",
        description="A compact speaker array for desktop personal sound zones.",
        rationale="Combines beamforming and pressure matching.",
        maturity="simulated",
        form_factor=FormFactor(type="desktop_bar", placement="under_monitor", listener_distance_cm="50-80"),
        use_case=UseCase(primary="private_desktop_audio", secondary=["speech_privacy"]),
        acoustic_architecture=AcousticArchitecture(
            control_stack=["beamforming"],
            calibration=["measured_transfer_functions"],
            simulation_backing=["room_impulse_response"],
        ),
        hardware=HardwareSpec(
            speakers={"estimated_count": 8, "geometry": "linear"},
            microphones={"calibration_count": "2"},
            compute={"prototype": "laptop"},
        ),
        expected_performance=ExpectedPerformance(bright_zone="15-20 dB contrast", latency="<10 ms"),
        unresolved_risks=["low_frequency_leakage"],
        next_steps=["build_simulation_bench"],
    ),
]


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


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


def _create_validated_approach(client, db_session, goal_id, method_family="beamforming"):
    _seed_evidence(db_session, goal_id, method_family)
    client.post(f"/co-scientist/goals/{goal_id}/approaches/generate",
                json={"method_families": [method_family]})
    approaches = client.get(f"/co-scientist/goals/{goal_id}/approaches").json()["items"]
    approach = next(a for a in approaches if a["method_family"] == method_family)
    client.post(f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/transition",
                json={"status": "reviewed"})
    client.post(f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/score", json={})
    for status in ["experiment_proposed", "tested", "validated"]:
        client.post(f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/transition",
                    json={"status": status})
    return approach


def test_generate_returns_201(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        resp = client.post(
            f"/co-scientist/goals/{goal['id']}/devices/generate",
            json={},
        )
    assert resp.status_code == 201
    assert resp.json()["generated"] == 1


def test_generate_wrong_goal_returns_404(client):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        resp = client.post(
            "/co-scientist/goals/nonexistent/devices/generate",
            json={},
        )
    assert resp.status_code == 404


def test_list_returns_200(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={})
        resp = client.get(f"/co-scientist/goals/{goal['id']}/devices")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_empty_returns_200(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/devices")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_get_returns_200(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        device_id = gen["items"][0]["id"]
        resp = client.get(f"/co-scientist/goals/{goal['id']}/devices/{device_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Near-field Desktop PSZ Bar"


def test_get_not_found_returns_404(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/devices/nonexistent")
    assert resp.status_code == 404


def test_transition_returns_200(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        device_id = gen["items"][0]["id"]
        resp = client.post(
            f"/co-scientist/goals/{goal['id']}/devices/{device_id}/transition",
            json={"status": "reviewed"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "reviewed"


def test_transition_invalid_returns_422(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        device_id = gen["items"][0]["id"]
        resp = client.post(
            f"/co-scientist/goals/{goal['id']}/devices/{device_id}/transition",
            json={"status": "generated"},
        )
    assert resp.status_code == 422


def test_export_markdown_returns_200(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        device_id = gen["items"][0]["id"]
        resp = client.get(
            f"/co-scientist/goals/{goal['id']}/devices/{device_id}/export?format=markdown"
        )
    assert resp.status_code == 200
    assert "## Form Factor" in resp.json()["content"]


def test_export_json_returns_200(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        device_id = gen["items"][0]["id"]
        resp = client.get(
            f"/co-scientist/goals/{goal['id']}/devices/{device_id}/export?format=json"
        )
    assert resp.status_code == 200
    data = json.loads(resp.json()["content"])
    assert data["name"] == "Near-field Desktop PSZ Bar"


def test_delete_returns_204(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        device_id = gen["items"][0]["id"]
        resp = client.delete(f"/co-scientist/goals/{goal['id']}/devices/{device_id}")
    assert resp.status_code == 204


def test_delete_reviewed_returns_409(client, db_session):
    with patch("coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS):
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        device_id = gen["items"][0]["id"]
        client.post(
            f"/co-scientist/goals/{goal['id']}/devices/{device_id}/transition",
            json={"status": "reviewed"},
        )
        resp = client.delete(f"/co-scientist/goals/{goal['id']}/devices/{device_id}")
    assert resp.status_code == 409


def test_compare_returns_200(client, db_session):
    with patch("coscientist.services.device._run_device_agent") as mock_agent:
        goal = _create_goal(client)
        _create_validated_approach(client, db_session, goal["id"])
        mock_agent.return_value = MOCK_CONCEPTS + [
            AgentDeviceConceptItem(
                name="Headrest PSZ Array",
                maturity="theoretical",
                form_factor=FormFactor(type="headrest"),
                use_case=UseCase(primary="car_audio"),
                acoustic_architecture=AcousticArchitecture(),
                hardware=HardwareSpec(
                    speakers={"estimated_count": 4},
                    microphones={},
                    compute={},
                ),
                expected_performance=ExpectedPerformance(),
                unresolved_risks=["sensitivity"],
                next_steps=["prototype"],
            )
        ]
        gen = client.post(f"/co-scientist/goals/{goal['id']}/devices/generate", json={}).json()
        ids = ",".join(c["id"] for c in gen["items"])
        resp = client.get(f"/co-scientist/goals/{goal['id']}/devices/compare?ids={ids}")
    assert resp.status_code == 200
    assert len(resp.json()["concepts"]) == 2


def test_compare_single_id_returns_400(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/devices/compare?ids=single-id")
    assert resp.status_code == 400
