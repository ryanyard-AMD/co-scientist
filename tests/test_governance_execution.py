"""Tests for CS-EPIC-GOVERNANCE: execution boundary + handoff audit trail."""

import pytest
from fastapi import HTTPException

from conftest import GOAL_PAYLOAD
from coscientist.config import settings
from coscientist.services import governance as governance_svc
from test_approval_api import _create_reviewed_experiment, _create_scored_approach

PREFIX = "/co-scientist"


def _submitted_experiment(client, goal_id, approach_id):
    exp = _create_reviewed_experiment(client, goal_id, approach_id)
    client.post(f"{PREFIX}/goals/{goal_id}/experiments/{exp['id']}/approve", json={})
    sub = client.post(
        f"{PREFIX}/goals/{goal_id}/experiments/{exp['id']}/submit",
        json={"approver": "dr-who"},
    ).json()
    return exp, sub


def test_handoff_submission_is_audited(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp, sub = _submitted_experiment(client, goal["id"], approach["id"])

    logs = client.get(f"{PREFIX}/goals/{goal['id']}/execution-audit").json()
    handoffs = [l for l in logs["items"] if l["action"] == "handoff_submitted"]
    assert len(handoffs) == 1
    entry = handoffs[0]
    assert entry["experiment_id"] == exp["id"]
    assert entry["actor"] == "dr-who"
    assert entry["execution_batch_id"] == sub["execution_batch_id"]
    assert entry["approval_id"] is not None
    assert entry["run_request_ids"] == [r["run_request_id"] for r in sub["runs"]]
    assert entry["policy"]["approver"] == "dr-who"
    assert entry["payload_checksum"]


def test_run_status_update_is_audited(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    _, sub = _submitted_experiment(client, goal["id"], approach["id"])
    rr_id = sub["runs"][0]["run_request_id"]

    client.post(f"{PREFIX}/run-requests/{rr_id}/status", json={"status": "running"})

    logs = client.get(
        f"{PREFIX}/goals/{goal['id']}/execution-audit",
        params={"action": "run_status_updated"},
    ).json()
    assert logs["total"] >= 1
    assert any(rr_id in l["run_request_ids"] and l["detail"]["status"] == "running" for l in logs["items"])


def test_result_bundle_ingestion_is_audited(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp, sub = _submitted_experiment(client, goal["id"], approach["id"])
    rr_id = sub["runs"][0]["run_request_id"]

    client.post(
        f"{PREFIX}/result-bundles",
        json={
            "result_bundle_id": "rb-1",
            "run_request_id": rr_id,
            "experiment_id": exp["id"],
            "validation_status": "passed",
            "metrics": {"acoustic_contrast": 22.0},
        },
    )

    logs = client.get(
        f"{PREFIX}/goals/{goal['id']}/execution-audit",
        params={"action": "result_bundle_ingested"},
    ).json()
    assert logs["total"] == 1
    entry = logs["items"][0]
    assert entry["experiment_id"] == exp["id"]
    assert entry["run_request_ids"] == [rr_id]
    assert entry["detail"]["result_bundle_id"] == "rb-1"
    assert entry["payload_checksum"]


def test_audit_filters_by_experiment(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp_a, _ = _submitted_experiment(client, goal["id"], approach["id"])
    exp_b, _ = _submitted_experiment(client, goal["id"], approach["id"])

    logs = client.get(
        f"{PREFIX}/goals/{goal['id']}/execution-audit",
        params={"experiment_id": exp_a["id"]},
    ).json()
    assert logs["total"] == 1
    assert all(l["experiment_id"] == exp_a["id"] for l in logs["items"])


def test_execution_boundary_blocks_direct_execution(monkeypatch):
    monkeypatch.setattr(settings, "enforce_execution_boundary", True)
    with pytest.raises(HTTPException) as exc:
        governance_svc.assert_execution_boundary("run experiments")
    assert exc.value.status_code == 403


def test_execution_boundary_allows_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "enforce_execution_boundary", False)
    governance_svc.assert_execution_boundary("run experiments")  # no raise


def test_payload_checksum_is_stable_and_order_independent():
    a = governance_svc.payload_checksum({"x": 1, "y": [1, 2]})
    b = governance_svc.payload_checksum({"y": [1, 2], "x": 1})
    assert a == b
    assert a != governance_svc.payload_checksum({"x": 2, "y": [1, 2]})
