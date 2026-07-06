"""Tests for CS-EPIC-APPROVAL RunRequest submission (approved card -> RunRequests)."""

from conftest import GOAL_PAYLOAD
from test_approval_api import _create_scored_approach, _create_reviewed_experiment

PREFIX = "/co-scientist"


def _approved_experiment(client, db_session, method_family="beamforming"):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"], method_family)
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    return goal, exp


def test_submit_approved_experiment_creates_batch(client, db_session):
    goal, exp = _approved_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["execution_batch_id"]
    assert body["run_request_count"] >= 1
    assert body["handoff_status"] == "submitted"
    assert body["execution_status"] == "submitted"
    assert all(r["status"] == "pending" for r in body["runs"])


def test_submit_stores_ids_on_card(client, db_session):
    goal, exp = _approved_experiment(client, db_session)
    resp = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    batch_id = resp.json()["execution_batch_id"]
    card = client.get(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}").json()
    assert card["execution_handoff"]["execution_batch_id"] == batch_id
    assert len(card["execution_handoff"]["run_request_ids"]) == resp.json()["run_request_count"]


def test_submit_requires_approved_status(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    assert resp.status_code == 409


def test_submit_twice_is_rejected(client, db_session):
    goal, exp = _approved_experiment(client, db_session)
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    resp = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    assert resp.status_code == 409


def test_approve_each_run_blocks_runs(client, db_session):
    goal, exp = _approved_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit",
        json={"approval_mode": "approve_each_run"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert all(r["status"] == "blocked" for r in body["runs"])
    assert body["execution_status"] == "blocked"


def test_threshold_mode_blocks_above_threshold(client, db_session):
    goal, exp = _approved_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit",
        json={"approval_mode": "approval_required_above_threshold", "approval_threshold": 0},
    )
    body = resp.json()
    assert all(r["status"] == "blocked" for r in body["runs"])


def test_approval_policy_stored_on_batch(client, db_session):
    goal, exp = _approved_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit",
        json={"approver": "dr-who", "credentialed": True, "cost_class": "high"},
    )
    batch_id = resp.json()["execution_batch_id"]
    batch = client.get(f"{PREFIX}/execution-batches/{batch_id}").json()
    policy = batch["approval_policy"]
    assert policy["approver"] == "dr-who"
    assert policy["credentialed"] is True
    assert policy["cost_class"] == "high"
    assert "approval_id" in policy
    assert "retry_policy" in policy
    assert "required_capabilities" in policy["resource_policy"]


def test_submit_run_requests_are_listable(client, db_session):
    goal, exp = _approved_experiment(client, db_session)
    resp = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    batch_id = resp.json()["execution_batch_id"]
    listed = client.get(f"{PREFIX}/run-requests", params={"batch_id": batch_id}).json()
    assert listed["total"] == resp.json()["run_request_count"]
