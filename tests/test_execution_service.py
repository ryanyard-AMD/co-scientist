"""Service + API tests for CS-EPIC-EXECUTION (batch/run tracking references)."""

import uuid

import pytest

from coscientist.schemas.execution import (
    RunAttemptCreate,
    RunAttemptStatusEnum,
    RunRequestStatusEnum,
    RunStatusUpdate,
)
from coscientist.services import execution as svc


def _ids():
    return {
        "experiment_id": str(uuid.uuid4()),
        "goal_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
    }


def _make_batch(db, **overrides):
    ids = _ids()
    ids.update(overrides)
    return svc.create_execution_batch(db, submission_mode="run_request_batch", **ids)


def _register(db, batch, status=RunRequestStatusEnum.pending):
    return svc.register_run_request(
        db,
        run_request_id=f"rr-{uuid.uuid4().hex}",
        experiment_id=batch.experiment_id,
        goal_id=batch.goal_id,
        workspace_id=batch.workspace_id,
        execution_batch_id=batch.id,
        status=status,
    )


# ---------------------------------------------------------------------------
# Batch + run request creation
# ---------------------------------------------------------------------------

def test_create_batch_defaults(db_session):
    batch = _make_batch(db_session)
    assert batch.aggregate_status == "submitted"
    assert batch.correlation_id.startswith("corr-")
    assert batch.total_count == 0


def test_register_run_request_is_idempotent(db_session):
    batch = _make_batch(db_session)
    rr_id = f"rr-{uuid.uuid4().hex}"
    first = svc.register_run_request(
        db_session,
        run_request_id=rr_id,
        experiment_id=batch.experiment_id,
        goal_id=batch.goal_id,
        workspace_id=batch.workspace_id,
        execution_batch_id=batch.id,
    )
    second = svc.register_run_request(
        db_session,
        run_request_id=rr_id,
        experiment_id=batch.experiment_id,
        goal_id=batch.goal_id,
        workspace_id=batch.workspace_id,
        execution_batch_id=batch.id,
    )
    assert first.id == second.id


def test_register_recomputes_batch_total(db_session):
    batch = _make_batch(db_session)
    _register(db_session, batch)
    _register(db_session, batch)
    refreshed = svc.get_batch(db_session, batch.id)
    assert refreshed.counts.total == 2


# ---------------------------------------------------------------------------
# Status ingestion + aggregate rollup
# ---------------------------------------------------------------------------

def test_status_update_rolls_up_to_running(db_session):
    batch = _make_batch(db_session)
    r1 = _register(db_session, batch)
    _register(db_session, batch)
    svc.apply_run_status_update(
        db_session, r1.run_request_id, RunStatusUpdate(status=RunRequestStatusEnum.running)
    )
    refreshed = svc.get_batch(db_session, batch.id)
    assert refreshed.aggregate_status.value == "running"
    assert refreshed.counts.running == 1


def test_all_completed_rolls_up_to_completed(db_session):
    batch = _make_batch(db_session)
    runs = [_register(db_session, batch) for _ in range(3)]
    for r in runs:
        svc.apply_run_status_update(
            db_session, r.run_request_id, RunStatusUpdate(status=RunRequestStatusEnum.completed)
        )
    refreshed = svc.get_batch(db_session, batch.id)
    assert refreshed.aggregate_status.value == "completed"


def test_mixed_terminal_rolls_up_to_mixed_outcome(db_session):
    batch = _make_batch(db_session)
    r1 = _register(db_session, batch)
    r2 = _register(db_session, batch)
    svc.apply_run_status_update(
        db_session, r1.run_request_id, RunStatusUpdate(status=RunRequestStatusEnum.completed)
    )
    svc.apply_run_status_update(
        db_session, r2.run_request_id, RunStatusUpdate(status=RunRequestStatusEnum.failed)
    )
    refreshed = svc.get_batch(db_session, batch.id)
    assert refreshed.aggregate_status.value == "mixed_outcome"


def test_partial_completion(db_session):
    batch = _make_batch(db_session)
    r1 = _register(db_session, batch)
    _register(db_session, batch)
    svc.apply_run_status_update(
        db_session, r1.run_request_id, RunStatusUpdate(status=RunRequestStatusEnum.completed)
    )
    refreshed = svc.get_batch(db_session, batch.id)
    assert refreshed.aggregate_status.value == "partially_completed"


def test_status_update_unknown_run_404(db_session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        svc.apply_run_status_update(
            db_session, "does-not-exist", RunStatusUpdate(status=RunRequestStatusEnum.running)
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------

def test_record_and_list_attempts(db_session):
    batch = _make_batch(db_session)
    r = _register(db_session, batch)
    svc.record_run_attempt(
        db_session,
        r.run_request_id,
        RunAttemptCreate(attempt_id="a-1", status=RunAttemptStatusEnum.running),
    )
    svc.record_run_attempt(
        db_session,
        r.run_request_id,
        RunAttemptCreate(
            attempt_id="a-2",
            status=RunAttemptStatusEnum.failed,
            failure_summary="oom",
        ),
    )
    attempts, total = svc.list_attempts(db_session, r.run_request_id)
    assert total == 2
    assert attempts[-1].failure_summary == "oom"


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

PREFIX = "/co-scientist"


def test_api_batch_lifecycle(client):
    ids = _ids()
    resp = client.post(
        f"{PREFIX}/execution-batches",
        json={**ids, "submission_mode": "run_request_batch"},
    )
    assert resp.status_code == 201, resp.text
    batch_id = resp.json()["id"]

    rr_id = f"rr-{uuid.uuid4().hex}"
    resp = client.post(
        f"{PREFIX}/run-requests",
        json={
            "run_request_id": rr_id,
            "experiment_id": ids["experiment_id"],
            "goal_id": ids["goal_id"],
            "workspace_id": ids["workspace_id"],
            "execution_batch_id": batch_id,
        },
    )
    assert resp.status_code == 201, resp.text

    resp = client.post(
        f"{PREFIX}/run-requests/{rr_id}/status", json={"status": "completed"}
    )
    assert resp.status_code == 200

    resp = client.get(f"{PREFIX}/execution-batches/{batch_id}")
    assert resp.json()["aggregate_status"] == "completed"

    resp = client.get(f"{PREFIX}/goals/{ids['goal_id']}/execution-batches")
    assert resp.json()["total"] == 1


def test_api_run_request_not_found(client):
    resp = client.get(f"{PREFIX}/run-requests/nope")
    assert resp.status_code == 404
