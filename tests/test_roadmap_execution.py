"""Tests for CS-EPIC-ROADMAP: roadmap updates from execution outcomes."""

import json
import uuid
from datetime import datetime, timezone

from conftest import GOAL_PAYLOAD
from coscientist.models.roadmap import ResearchRoadmapItem
from test_approval_api import _create_scored_approach

PREFIX = "/co-scientist"
FOLLOWUP_RUN_ID = "execution-followup"


def _bundle(experiment_id, run_request_id, status="passed", attempt_id="1", **extra):
    body = {
        "result_bundle_id": f"rb-{run_request_id}-{attempt_id}",
        "run_request_id": run_request_id,
        "attempt_id": attempt_id,
        "experiment_id": experiment_id,
        "validation_status": status,
        "metrics": {"acoustic_contrast": 22.0},
    }
    body.update(extra)
    return body


def _seed_item(db, goal_id, exp_id, approach_id, **kw):
    now = datetime.now(timezone.utc)
    item = ResearchRoadmapItem(
        id=str(uuid.uuid4()),
        workspace_id=goal_id,
        title=kw.get("title", "Run the planned experiment"),
        description="Planned experiment roadmap item",
        lane=kw.get("lane", "conservative"),
        status=kw.get("status", "open"),
        priority_score=kw.get("priority_score", 0.6),
        priority_rank=kw.get("priority_rank", 1),
        rationale="seed",
        estimated_cost=kw.get("estimated_cost", "medium"),
        estimated_information_gain=kw.get("estimated_information_gain", "medium"),
        source_approach_ids=json.dumps([approach_id] if approach_id else []),
        source_experiment_id=exp_id,
        source_device_id=kw.get("source_device_id"),
        generation_run_id=kw.get("generation_run_id", str(uuid.uuid4())),
        model_used="test-model",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    return item


def _setup(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments",
        json={
            "name": "Roadmap Experiment",
            "objective": "Evaluate method",
            "hypothesis_text": "Method achieves target",
            "approach_ids": [approach["id"]],
        },
    ).json()
    return goal, approach, exp


def _roadmap(client, goal_id):
    return client.get(f"{PREFIX}/goals/{goal_id}/roadmap").json()["items"]


def _followups(client, goal_id):
    return [i for i in _roadmap(client, goal_id) if i["generation_run_id"] == FOLLOWUP_RUN_ID]


def test_passed_experiment_completes_linked_item(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    item = _seed_item(db_session, goal["id"], exp["id"], approach["id"])

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    updated = next(i for i in _roadmap(client, goal["id"]) if i["id"] == item.id)
    assert updated["status"] == "completed"
    assert updated["execution_outcome"] == "passed"
    assert updated["provisional"] is False


def test_failed_experiment_completes_item_and_creates_followups(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    item = _seed_item(db_session, goal["id"], exp["id"], approach["id"])

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="failed"))

    updated = next(i for i in _roadmap(client, goal["id"]) if i["id"] == item.id)
    assert updated["status"] == "completed"
    assert updated["execution_outcome"] == "failed"

    followups = _followups(client, goal["id"])
    assert len(followups) == 5
    titles = {f["title"] for f in followups}
    assert "Rerun experiment with changed assumptions" in titles
    assert "Add a baseline comparison" in titles
    # Follow-ups inherit the source experiment + approaches so they stay linked.
    assert all(f["source_experiment_id"] == exp["id"] for f in followups)
    assert all(approach["id"] in f["source_approach_ids"] for f in followups)


def test_inconclusive_experiment_keeps_item_open(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    item = _seed_item(db_session, goal["id"], exp["id"], approach["id"])

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="blocked"))

    updated = next(i for i in _roadmap(client, goal["id"]) if i["id"] == item.id)
    assert updated["status"] == "open"
    assert updated["execution_outcome"] == "inconclusive"
    assert _followups(client, goal["id"]) == []


def test_failure_followups_are_idempotent(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    _seed_item(db_session, goal["id"], exp["id"], approach["id"])

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="failed"))
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-2", status="failed"))

    assert len(_followups(client, goal["id"])) == 5


def test_ranking_adjusts_with_evidence(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    _seed_item(db_session, goal["id"], exp["id"], approach["id"], priority_score=0.6)

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="failed"))

    items = _roadmap(client, goal["id"])
    # Every item now carries a validation-aware score and a fresh rank.
    assert all(i["evidence_adjusted_score"] is not None for i in items)
    # Actionable failure follow-ups outrank the now-completed planned item.
    top = items[0]
    assert top["generation_run_id"] == FOLLOWUP_RUN_ID
    ranks = [i["priority_rank"] for i in items]
    assert sorted(ranks) == list(range(1, len(items) + 1))


def test_partial_batch_creates_provisional_followups(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    item = _seed_item(db_session, goal["id"], exp["id"], approach["id"])

    client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(exp["id"], "rr-1", status="failed", is_partial=True),
    )

    updated = next(i for i in _roadmap(client, goal["id"]) if i["id"] == item.id)
    # Planned item stays open and is flagged provisional until the batch finishes.
    assert updated["status"] == "open"
    assert updated["provisional"] is True

    followups = _followups(client, goal["id"])
    assert len(followups) == 5
    assert all(f["provisional"] is True for f in followups)


def test_partial_followups_confirmed_on_final_failure(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    _seed_item(db_session, goal["id"], exp["id"], approach["id"])

    client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(exp["id"], "rr-1", status="failed", is_partial=True),
    )
    # Same run finishes (later attempt, no longer partial) confirming the failure.
    client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(exp["id"], "rr-1", status="failed", attempt_id="2", is_partial=False),
    )

    followups = _followups(client, goal["id"])
    assert len(followups) == 5
    assert all(f["provisional"] is False for f in followups)


def test_partial_followups_superseded_on_final_pass(client, db_session):
    goal, approach, exp = _setup(client, db_session)
    _seed_item(db_session, goal["id"], exp["id"], approach["id"])

    client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(exp["id"], "rr-1", status="failed", is_partial=True),
    )
    # Batch finishes green — the early-failure follow-ups are replaced.
    client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(exp["id"], "rr-1", status="passed", attempt_id="2", is_partial=False),
    )

    followups = _followups(client, goal["id"])
    assert all(f["status"] == "superseded" for f in followups)
