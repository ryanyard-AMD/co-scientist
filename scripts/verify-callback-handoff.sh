#!/usr/bin/env bash
#
# Verify the co-scientist -> repro -> co-scientist callback handoff loop.
#
# Usage:
#   scripts/verify-callback-handoff.sh GOAL_ID SOURCE_EXPERIMENT_ID
#
# Environment:
#   CS_API_BASE              default: http://localhost:8001/co-scientist
#   REPRO_API_BASE           default: http://localhost:8003
#   CONTROL_PLANE_URI        default: $REPRO_API_BASE
#   EXPERIMENT_REPO          default: /home/ryard/experiment
#   EXP_RUNNER               default: $EXPERIMENT_REPO/.venv/bin/exp-runner
#   SMOKE_RUNNER_ID          default: generated
#   SMOKE_MAX_WORKER_JOBS    default: 5
#   SMOKE_WORKER_TIMEOUT     default: 900 seconds
#   SMOKE_CALLBACK_TIMEOUT   default: 120 seconds
#   SMOKE_ARCHIVE_ON_SUCCESS default: 0
set -euo pipefail

usage() {
  sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi

export GOAL_ID="$1"
export SOURCE_EXPERIMENT_ID="$2"
export CS_API_BASE="${CS_API_BASE:-http://localhost:8001/co-scientist}"
export REPRO_API_BASE="${REPRO_API_BASE:-http://localhost:8003}"
export CONTROL_PLANE_URI="${CONTROL_PLANE_URI:-$REPRO_API_BASE}"
export EXPERIMENT_REPO="${EXPERIMENT_REPO:-/home/ryard/experiment}"
export EXP_RUNNER="${EXP_RUNNER:-$EXPERIMENT_REPO/.venv/bin/exp-runner}"
export SMOKE_RUNNER_ID="${SMOKE_RUNNER_ID:-cosci-callback-smoke-$(date +%Y%m%d%H%M%S)}"
export SMOKE_MAX_WORKER_JOBS="${SMOKE_MAX_WORKER_JOBS:-5}"
export SMOKE_WORKER_TIMEOUT="${SMOKE_WORKER_TIMEOUT:-900}"
export SMOKE_CALLBACK_TIMEOUT="${SMOKE_CALLBACK_TIMEOUT:-120}"
export SMOKE_ARCHIVE_ON_SUCCESS="${SMOKE_ARCHIVE_ON_SUCCESS:-0}"

"$PYTHON" <<'PY'
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


GOAL_ID = os.environ["GOAL_ID"]
SOURCE_EXPERIMENT_ID = os.environ["SOURCE_EXPERIMENT_ID"]
CS = os.environ["CS_API_BASE"].rstrip("/")
REPRO = os.environ["REPRO_API_BASE"].rstrip("/")
CONTROL_PLANE_URI = os.environ["CONTROL_PLANE_URI"].rstrip("/")
EXPERIMENT_REPO = Path(os.environ["EXPERIMENT_REPO"])
EXP_RUNNER = Path(os.environ["EXP_RUNNER"])
RUNNER_ID = os.environ["SMOKE_RUNNER_ID"]
MAX_WORKER_JOBS = int(os.environ["SMOKE_MAX_WORKER_JOBS"])
WORKER_TIMEOUT = float(os.environ["SMOKE_WORKER_TIMEOUT"])
CALLBACK_TIMEOUT = float(os.environ["SMOKE_CALLBACK_TIMEOUT"])
ARCHIVE_ON_SUCCESS = os.environ["SMOKE_ARCHIVE_ON_SUCCESS"] == "1"

TERMINAL_REPRO_STATES = {"completed", "failed", "canceled", "timed_out", "abandoned"}


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def http_json(method: str, url: str, body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        fail(f"{method} {url} returned HTTP {exc.code}: {raw[:1000]}")
    except Exception as exc:
        fail(f"{method} {url} failed: {exc}")


def cs(path: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    return http_json(method, f"{CS}{path}", body=body, timeout=timeout)


def repro(path: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    return http_json(method, f"{REPRO}{path}", body=body, timeout=timeout)


def run_worker_once(iteration: int) -> None:
    cmd = [
        str(EXP_RUNNER),
        "worker",
        "--runner-id",
        RUNNER_ID,
        "--runtime",
        "python-numerics",
        "--label",
        "python_numerics",
        "--max-concurrent",
        "1",
        "--runs-root",
        "runs",
        "--max-iterations",
        "1",
    ]
    log(f"worker iteration {iteration}: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=EXPERIMENT_REPO,
        text=True,
        capture_output=True,
        timeout=WORKER_TIMEOUT,
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        fail(f"worker exited with code {proc.returncode}")


def main() -> None:
    if not EXPERIMENT_REPO.is_dir():
        fail(f"EXPERIMENT_REPO does not exist: {EXPERIMENT_REPO}")
    if not EXP_RUNNER.is_file():
        fail(f"EXP_RUNNER does not exist: {EXP_RUNNER}")

    log("checking APIs")
    cs("/health")
    repro("/api/v1/workspaces", timeout=30)

    log(f"duplicating experiment {SOURCE_EXPERIMENT_ID}")
    duplicate = cs(
        f"/goals/{GOAL_ID}/experiments/{SOURCE_EXPERIMENT_ID}/duplicate",
        method="POST",
    )
    experiment_id = duplicate["new_id"]
    print(f"experiment_id={experiment_id}")

    log("setting control-plane URI")
    cs(
        f"/goals/{GOAL_ID}/experiments/{experiment_id}",
        method="PATCH",
        body={"experiment_control_plane": CONTROL_PLANE_URI},
    )

    log("running execution preflight")
    preflight = cs(
        f"/goals/{GOAL_ID}/experiments/{experiment_id}/preflight",
        method="POST",
        timeout=180,
    )
    if not preflight.get("runnable"):
        fail("preflight was not runnable: " + json.dumps(preflight.get("blocking_reasons"), indent=2))
    print(f"selected_reproduction_id={preflight.get('selected_reproduction_id')}")
    if preflight.get("warnings"):
        print("preflight_warnings=" + json.dumps(preflight["warnings"]))

    log("reviewing and approving experiment")
    cs(
        f"/goals/{GOAL_ID}/experiments/{experiment_id}/transition",
        method="POST",
        body={"status": "reviewed"},
    )
    cs(
        f"/goals/{GOAL_ID}/experiments/{experiment_id}/approve",
        method="POST",
        body={
            "reviewer_id": RUNNER_ID,
            "reason": "Callback handoff smoke verification",
        },
    )

    log("submitting experiment")
    submission = cs(
        f"/goals/{GOAL_ID}/experiments/{experiment_id}/submit",
        method="POST",
        body={"approver": RUNNER_ID, "credentialed": True},
        timeout=180,
    )
    runs = submission.get("runs") or []
    if not runs:
        fail("submit response contained no runs")
    run_request_id = runs[0]["run_request_id"]
    print(f"run_request_id={run_request_id}")

    record = repro(f"/api/v1/run-requests/{run_request_id}", timeout=30)
    callback = (record.get("request") or {}).get("callback") or {}
    if callback.get("url") != f"{CS}/result-bundles":
        fail(f"unexpected callback URL: {callback.get('url')!r}")

    for i in range(1, MAX_WORKER_JOBS + 1):
        record = repro(f"/api/v1/run-requests/{run_request_id}", timeout=30)
        state = record.get("state")
        print(f"repro_state_before_worker={state}")
        if state in TERMINAL_REPRO_STATES:
            break
        run_worker_once(i)
    record = repro(f"/api/v1/run-requests/{run_request_id}", timeout=30)
    state = record.get("state")
    print(f"repro_state={state}")
    if state != "completed":
        fail(f"repro run did not complete; final state={state!r}")

    events = repro(f"/api/v1/runs/{run_request_id}/events", timeout=30)
    event_types = [event.get("event_type") for event in events]
    if "callback_delivered" not in event_types:
        fail("repro did not record callback_delivered")

    log("waiting for co-scientist callback ingestion")
    deadline = time.monotonic() + CALLBACK_TIMEOUT
    bundles = None
    aggregation = None
    run_ref = None
    while time.monotonic() < deadline:
        bundles = cs(f"/experiments/{experiment_id}/result-bundles", timeout=30)
        aggregation = cs(f"/experiments/{experiment_id}/validation-aggregation", timeout=30)
        run_ref = cs(f"/run-requests/{run_request_id}", timeout=30)
        if bundles.get("total", 0) >= 1 and run_ref.get("status") == "completed":
            break
        time.sleep(2)
    else:
        fail("co-scientist did not ingest callback ResultBundle before timeout")

    if aggregation.get("aggregate_status") != "passed":
        fail("co-scientist aggregation is not passed: " + json.dumps(aggregation, indent=2))

    health = cs(f"/goals/{GOAL_ID}/evaluation/callback-health", timeout=30)
    if run_request_id in set(health.get("missing_run_request_ids") or []):
        fail("callback-health reports this run as missing")
    if not health.get("callback_ingest_meets_target"):
        fail("callback-health gate failed: " + json.dumps(health, indent=2))

    if ARCHIVE_ON_SUCCESS:
        log("archiving verification duplicate")
        cs(
            f"/goals/{GOAL_ID}/experiments/{experiment_id}/transition",
            method="POST",
            body={"status": "archived"},
        )

    log("callback handoff smoke passed")
    print("summary=" + json.dumps(
        {
            "goal_id": GOAL_ID,
            "experiment_id": experiment_id,
            "run_request_id": run_request_id,
            "repro_state": state,
            "bundle_count": bundles.get("total"),
            "aggregate_status": aggregation.get("aggregate_status"),
            "callback_health_rate": health.get("callback_ingest_rate"),
        },
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
PY
