import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _seed_evidence(db, workspace_id, method_family):
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


def _create_scored_approach(client, db_session, goal_id, method_family="beamforming"):
    _seed_evidence(db_session, goal_id, method_family)
    client.post(f"/co-scientist/goals/{goal_id}/approaches/generate",
                json={"method_families": [method_family]})
    approaches = client.get(f"/co-scientist/goals/{goal_id}/approaches").json()["items"]
    approach = next(a for a in approaches if a["method_family"] == method_family)
    client.post(f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/transition",
                json={"status": "reviewed"})
    client.post(f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/score", json={})
    return approach


def _create_reviewed_experiment(client, goal_id, approach_id):
    resp = client.post(f"/co-scientist/goals/{goal_id}/experiments", json={
        "name": "Test Experiment",
        "objective": "Evaluate method",
        "hypothesis_text": "Method achieves target",
        "approach_ids": [approach_id],
    })
    exp = resp.json()
    client.post(f"/co-scientist/goals/{goal_id}/experiments/{exp['id']}/transition",
                json={"status": "reviewed"})
    return exp


def test_list_pending_returns_200(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/pending")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_list_pending_filters_by_goal(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/pending")
    assert resp.status_code == 200
    body = resp.json()
    assert all(e["workspace_id"] == goal["id"] for e in body)


def test_approve_returns_201(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    assert resp.status_code == 201
    assert resp.json()["decision"] == "approve"


def test_approve_transitions_experiment(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    client.post(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    updated = client.get(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}").json()
    assert updated["status"] == "approved"


def test_approve_goal_not_found(client):
    resp = client.post("/co-scientist/goals/nonexistent-goal/experiments/nonexistent/approve", json={})
    assert resp.status_code == 404


def test_approve_experiment_not_found(client):
    goal = _create_goal(client)
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments/nonexistent/approve", json={})
    assert resp.status_code == 404


def test_approve_experiment_not_reviewed_returns_409(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    # experiment in "generated" status
    exp = client.post(f"/co-scientist/goals/{goal['id']}/experiments", json={
        "name": "Not Reviewed",
        "objective": "Test",
        "hypothesis_text": "Hypothesis",
        "approach_ids": [approach["id"]],
    }).json()
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    assert resp.status_code == 409


def test_reject_returns_201(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/reject",
        json={"reason": "Not feasible"},
    )
    assert resp.status_code == 201
    assert resp.json()["decision"] == "reject"


def test_reject_missing_reason_returns_422(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/reject",
        json={},
    )
    assert resp.status_code == 422


def test_request_edit_returns_201(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/request-edit",
        json={"reason": "Needs more baselines"},
    )
    assert resp.status_code == 201
    assert resp.json()["decision"] == "request_edit"
    updated = client.get(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}").json()
    assert updated["status"] == "generated"


def test_request_edit_missing_reason_returns_422(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/request-edit",
        json={},
    )
    assert resp.status_code == 422


def test_list_decisions_returns_200(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    client.post(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/decisions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["decision"] == "approve"


def test_duplicate_returns_201(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/duplicate")
    assert resp.status_code == 201
    body = resp.json()
    assert body["original_id"] == exp["id"]
    assert body["new_id"] != exp["id"]
    assert body["new_experiment"]["status"] == "generated"
    assert "(copy)" in body["new_experiment"]["name"]


def test_duplicate_not_found_returns_404(client):
    goal = _create_goal(client)
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments/nonexistent/duplicate")
    assert resp.status_code == 404
