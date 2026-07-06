"""Tests for CS-EPIC-DEVICE: device concept updates from execution evidence."""

from unittest.mock import patch

from conftest import GOAL_PAYLOAD
from test_approval_api import _create_scored_approach
from test_device_service import MOCK_CONCEPTS

PREFIX = "/co-scientist"


def _bundle(experiment_id, run_request_id, status="passed", **extra):
    body = {
        "result_bundle_id": f"rb-{run_request_id}",
        "run_request_id": run_request_id,
        "attempt_id": "1",
        "experiment_id": experiment_id,
        "validation_status": status,
        "metrics": {"acoustic_contrast": 22.0},
    }
    body.update(extra)
    return body


def _setup(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    with patch(
        "coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS
    ):
        gen = client.post(
            f"{PREFIX}/goals/{goal['id']}/devices/generate", json={}
        ).json()
    device = gen["items"][0]
    exp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments",
        json={
            "name": "Device Experiment",
            "objective": "Evaluate method",
            "hypothesis_text": "Method achieves target",
            "approach_ids": [approach["id"]],
        },
    ).json()
    return goal, approach, device, exp


def _device(client, goal_id, device_id):
    return client.get(f"{PREFIX}/goals/{goal_id}/devices/{device_id}").json()


def test_generate_starts_confidence_neutral(client, db_session):
    goal, approach, device, exp = _setup(client, db_session)
    assert device["confidence"] == 0.5


def test_passed_experiment_raises_confidence(client, db_session):
    goal, approach, device, exp = _setup(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    after = _device(client, goal["id"], device["id"])
    assert after["confidence"] > 0.5


def test_failed_experiment_lowers_confidence_and_adds_risk(client, db_session):
    goal, approach, device, exp = _setup(client, db_session)
    client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(
            exp["id"],
            "rr-1",
            status="failed",
            failure_type="latency_budget",
            failure_summary="Latency budget exceeded",
        ),
    )

    after = _device(client, goal["id"], device["id"])
    assert after["confidence"] < 0.5
    assert any("Latency risk" in r for r in after["unresolved_risks"])


def test_execution_evidence_reports_experiment_outcomes(client, db_session):
    goal, approach, device, exp = _setup(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    ev = client.get(
        f"{PREFIX}/goals/{goal['id']}/devices/{device['id']}/execution-evidence"
    ).json()
    assert ev["passed_experiments"] == 1
    assert ev["failed_experiments"] == 0
    assert len(ev["experiments"]) == 1
    block = ev["experiments"][0]
    assert block["experiment_id"] == exp["id"]
    assert block["validation_status"] == "passed"
    assert "acoustic_contrast" in block["passing_metrics"]
    assert approach["id"] in ev["affected_approach_scores"]


def test_evidence_update_recorded_with_provenance(client, db_session):
    goal, approach, device, exp = _setup(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    updates = client.get(
        f"{PREFIX}/goals/{goal['id']}/devices/evidence-updates",
        params={"device_id": device["id"]},
    ).json()
    assert updates["total"] == 1
    u = updates["items"][0]
    assert u["confidence_delta"] > 0
    assert u["passed_experiments"] == 1
    assert u["supporting_result_bundle_refs"] == ["rb-rr-1"]
    assert approach["id"] in u["affected_approach_ids"]
    assert u["rationale"]


def test_duplicate_bundle_produces_no_second_update(client, db_session):
    goal, approach, device, exp = _setup(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))
    conf_first = _device(client, goal["id"], device["id"])["confidence"]

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    updates = client.get(
        f"{PREFIX}/goals/{goal['id']}/devices/evidence-updates",
        params={"device_id": device["id"]},
    ).json()
    assert updates["total"] == 1
    assert _device(client, goal["id"], device["id"])["confidence"] == conf_first


def test_comparison_includes_execution_evidence(client, db_session):
    goal, approach, device, exp = _setup(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    # A second device to compare against.
    with patch(
        "coscientist.services.device._run_device_agent", return_value=MOCK_CONCEPTS
    ):
        gen2 = client.post(f"{PREFIX}/goals/{goal['id']}/devices/generate", json={}).json()
    device2 = gen2["items"][0]

    comp = client.get(
        f"{PREFIX}/goals/{goal['id']}/devices/compare",
        params={"ids": f"{device['id']},{device2['id']}"},
    ).json()
    assert "validation_passed" in comp["dimensions"]
    assert "confidence" in comp["dimensions"]
    first = next(c for c in comp["concepts"] if c["id"] == device["id"])
    assert first["values"]["validation_passed"] == "1"
