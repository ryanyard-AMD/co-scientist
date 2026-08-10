#!/usr/bin/env bash
#
# Run an autonomous co-scientist goal rerun pipeline.
#
# Usage:
#   scripts/autonomous-goal-rerun.sh [--execute] [--method METHOD] GOAL_ID
#
# Default mode is safe planning only: it checks services and prints current
# state. --execute mutates the database, submits to repro, runs a local worker,
# and verifies callback ingestion.
#
# Environment:
#   CS_API_BASE              default: http://localhost:8001/co-scientist
#   REPRO_API_BASE           default: http://localhost:8003
#   CONTROL_PLANE_URI        default: $REPRO_API_BASE
#   EXPERIMENT_REPO          default: /home/ryard/experiment
#   EXP_RUNNER               default: $EXPERIMENT_REPO/.venv/bin/exp-runner
#   AUTORUN_TOP_K            default: 20
#   AUTORUN_MAX_FAMILIES     default: 12
#   AUTORUN_MIN_EVIDENCE     default: 2
#   AUTORUN_MAX_HYPOTHESES   default: 20
#   AUTORUN_MAX_EXPERIMENTS  default: 10
#   AUTORUN_SYNTHESIZE       default: 0
#   AUTORUN_ARCHIVE_SUCCESS  default: 0
set -euo pipefail

usage() {
  sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

EXECUTE=0
METHOD_FAMILY=""
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) EXECUTE=1; shift ;;
    --method|-m)
      [[ $# -ge 2 ]] || { echo "missing value for $1" >&2; exit 2; }
      METHOD_FAMILY="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
if [[ ${#ARGS[@]} -ne 1 ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi

export GOAL_ID="${ARGS[0]}"
export METHOD_FAMILY
export EXECUTE
export CS_API_BASE="${CS_API_BASE:-http://localhost:8001/co-scientist}"
export REPRO_API_BASE="${REPRO_API_BASE:-http://localhost:8003}"
export CONTROL_PLANE_URI="${CONTROL_PLANE_URI:-$REPRO_API_BASE}"
export EXPERIMENT_REPO="${EXPERIMENT_REPO:-/home/ryard/experiment}"
export EXP_RUNNER="${EXP_RUNNER:-$EXPERIMENT_REPO/.venv/bin/exp-runner}"
export AUTORUN_TOP_K="${AUTORUN_TOP_K:-20}"
export AUTORUN_MAX_FAMILIES="${AUTORUN_MAX_FAMILIES:-12}"
export AUTORUN_MIN_EVIDENCE="${AUTORUN_MIN_EVIDENCE:-2}"
export AUTORUN_MAX_HYPOTHESES="${AUTORUN_MAX_HYPOTHESES:-20}"
export AUTORUN_MAX_EXPERIMENTS="${AUTORUN_MAX_EXPERIMENTS:-10}"
export AUTORUN_SYNTHESIZE="${AUTORUN_SYNTHESIZE:-0}"
export AUTORUN_ARCHIVE_SUCCESS="${AUTORUN_ARCHIVE_SUCCESS:-0}"
export AUTORUN_RUNNER_ID="${AUTORUN_RUNNER_ID:-cosci-autonomous-$(date +%Y%m%d%H%M%S)}"
export AUTORUN_MAX_WORKER_JOBS="${AUTORUN_MAX_WORKER_JOBS:-8}"
export AUTORUN_WORKER_TIMEOUT="${AUTORUN_WORKER_TIMEOUT:-900}"
export AUTORUN_CALLBACK_TIMEOUT="${AUTORUN_CALLBACK_TIMEOUT:-120}"

"$PYTHON" <<'PY'
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GOAL_ID = os.environ["GOAL_ID"]
METHOD_FAMILY = os.environ.get("METHOD_FAMILY") or None
EXECUTE = os.environ["EXECUTE"] == "1"
CS = os.environ["CS_API_BASE"].rstrip("/")
REPRO = os.environ["REPRO_API_BASE"].rstrip("/")
CONTROL_PLANE_URI = os.environ["CONTROL_PLANE_URI"].rstrip("/")
EXPERIMENT_REPO = Path(os.environ["EXPERIMENT_REPO"])
EXP_RUNNER = Path(os.environ["EXP_RUNNER"])
RUNNER_ID = os.environ["AUTORUN_RUNNER_ID"]
TOP_K = int(os.environ["AUTORUN_TOP_K"])
MAX_FAMILIES = int(os.environ["AUTORUN_MAX_FAMILIES"])
MIN_EVIDENCE = int(os.environ["AUTORUN_MIN_EVIDENCE"])
MAX_HYPOTHESES = int(os.environ["AUTORUN_MAX_HYPOTHESES"])
MAX_EXPERIMENTS = int(os.environ["AUTORUN_MAX_EXPERIMENTS"])
SYNTHESIZE = os.environ["AUTORUN_SYNTHESIZE"] == "1"
ARCHIVE_SUCCESS = os.environ["AUTORUN_ARCHIVE_SUCCESS"] == "1"
MAX_WORKER_JOBS = int(os.environ["AUTORUN_MAX_WORKER_JOBS"])
WORKER_TIMEOUT = float(os.environ["AUTORUN_WORKER_TIMEOUT"])
CALLBACK_TIMEOUT = float(os.environ["AUTORUN_CALLBACK_TIMEOUT"])

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
        fail(f"{method} {url} returned HTTP {exc.code}: {raw[:1200]}")
    except Exception as exc:
        fail(f"{method} {url} failed: {exc}")


def qs(params: dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return "?" + urllib.parse.urlencode(clean) if clean else ""


def cs(path: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    return http_json(method, f"{CS}{path}", body=body, timeout=timeout)


def repro(path: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    return http_json(method, f"{REPRO}{path}", body=body, timeout=timeout)


def backup_db() -> Path:
    src = Path("coscientist.db")
    if not src.exists():
        fail("coscientist.db not found; refusing to execute without a DB backup")
    out = Path(f"coscientist.db.bak.autorun.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    s = sqlite3.connect(src)
    d = sqlite3.connect(out)
    with d:
        s.backup(d)
    s.close()
    result = d.execute("PRAGMA integrity_check").fetchone()[0]
    d.close()
    if result != "ok":
        print(f"WARNING: backup integrity_check: {result}", file=sys.stderr)
    return out


def list_items(path: str, **params) -> list[dict[str, Any]]:
    data = cs(path + qs(params), timeout=60)
    return data.get("items", data if isinstance(data, list) else [])


def plan_summary() -> None:
    goal = cs(f"/goals/{GOAL_ID}")
    approaches = list_items(f"/goals/{GOAL_ID}/approaches", limit=100)
    hypotheses = list_items(f"/goals/{GOAL_ID}/hypotheses", limit=100)
    experiments = list_items(f"/goals/{GOAL_ID}/experiments", limit=100)
    callback = cs(f"/goals/{GOAL_ID}/evaluation/callback-health")
    print("plan=" + json.dumps(
        {
            "goal": goal["name"],
            "method_filter": METHOD_FAMILY,
            "approaches": len(approaches),
            "hypotheses": len(hypotheses),
            "experiments": len(experiments),
            "callback_health": {
                "rate": callback["callback_ingest_rate"],
                "missing": callback["missing_callback_results"],
            },
            "execute": EXECUTE,
        },
        sort_keys=True,
    ))


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
    proc = subprocess.run(cmd, cwd=EXPERIMENT_REPO, text=True, capture_output=True, timeout=WORKER_TIMEOUT)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        fail(f"worker exited with code {proc.returncode}")


def transition_experiment(experiment_id: str, status: str) -> None:
    cs(
        f"/goals/{GOAL_ID}/experiments/{experiment_id}/transition",
        method="POST",
        body={"status": status},
    )


def review_generated_approaches() -> None:
    generated = list_items(f"/goals/{GOAL_ID}/approaches", status="generated", limit=100)
    for approach in generated:
        if METHOD_FAMILY and approach.get("method_family") != METHOD_FAMILY:
            continue
        cs(
            f"/goals/{GOAL_ID}/approaches/{approach['id']}/transition",
            method="POST",
            body={"status": "reviewed"},
        )
    if generated:
        log(f"reviewed generated approaches matching filter: {len(generated)}")


def review_generated_hypotheses() -> None:
    generated = list_items(f"/goals/{GOAL_ID}/hypotheses", status="generated", limit=100)
    for hyp in generated:
        cs(
            f"/goals/{GOAL_ID}/hypotheses/{hyp['id']}/transition",
            method="POST",
            body={"status": "reviewed"},
        )
    if generated:
        log(f"reviewed generated hypotheses: {len(generated)}")


def approach_method_index() -> dict[str, str]:
    approaches = list_items(f"/goals/{GOAL_ID}/approaches", limit=100)
    return {a["id"]: a.get("method_family") for a in approaches}


def candidate_experiments() -> list[dict[str, Any]]:
    method_by_approach = approach_method_index()
    experiments = list_items(f"/goals/{GOAL_ID}/experiments", limit=100)
    candidates = []
    for exp in experiments:
        if exp["status"] in {"archived", "superseded", "rejected"}:
            continue
        handoff = exp.get("execution_handoff") or {}
        if handoff.get("run_request_ids"):
            continue
        if exp.get("execution_status") not in {"not_submitted", "blocked"}:
            continue
        if METHOD_FAMILY:
            methods = {method_by_approach.get(aid) for aid in exp.get("approach_ids", [])}
            if METHOD_FAMILY not in methods:
                continue
        candidates.append(exp)
    # Prefer generated/reviewed fresh cards; then approved-but-not-submitted.
    rank = {"generated": 0, "reviewed": 1, "approved": 2}
    candidates.sort(key=lambda e: (rank.get(e["status"], 9), e.get("created_at", "")), reverse=False)
    return candidates


def duplicate_best_current_experiment() -> dict[str, Any]:
    method_by_approach = approach_method_index()
    experiments = list_items(f"/goals/{GOAL_ID}/experiments", limit=100)
    viable = []
    for exp in experiments:
        if exp["status"] in {"archived", "superseded", "rejected"}:
            continue
        if METHOD_FAMILY:
            methods = {method_by_approach.get(aid) for aid in exp.get("approach_ids", [])}
            if METHOD_FAMILY not in methods:
                continue
        viable.append(exp)
    status_rank = {"completed": 0, "approved": 1, "reviewed": 2, "generated": 3}
    viable.sort(key=lambda e: (status_rank.get(e["status"], 9), e.get("updated_at", "")))
    if not viable:
        fail("no viable experiment exists to duplicate after generation")
    source = viable[0]
    log(f"duplicating fallback experiment {source['id']}")
    duplicate = cs(f"/goals/{GOAL_ID}/experiments/{source['id']}/duplicate", method="POST")
    return duplicate["new_experiment"]


def choose_runnable_experiment() -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = candidate_experiments()
    if not candidates:
        candidates = [duplicate_best_current_experiment()]
    for exp in candidates:
        cs(
            f"/goals/{GOAL_ID}/experiments/{exp['id']}",
            method="PATCH",
            body={"experiment_control_plane": CONTROL_PLANE_URI},
        )
        preflight = cs(
            f"/goals/{GOAL_ID}/experiments/{exp['id']}/preflight",
            method="POST",
            timeout=180,
        )
        print(f"preflight {exp['id']} runnable={preflight.get('runnable')} selected={preflight.get('selected_reproduction_id')}")
        if preflight.get("warnings"):
            print("preflight_warnings=" + json.dumps(preflight["warnings"]))
        if preflight.get("runnable"):
            return exp, preflight
    fail("no runnable experiment candidate found")


def submit_and_execute(exp: dict[str, Any]) -> tuple[str, str]:
    exp_id = exp["id"]
    status = exp["status"]
    if status == "generated":
        transition_experiment(exp_id, "reviewed")
        status = "reviewed"
    if status == "reviewed":
        cs(
            f"/goals/{GOAL_ID}/experiments/{exp_id}/approve",
            method="POST",
            body={"reviewer_id": RUNNER_ID, "reason": "Autonomous goal rerun"},
        )
    elif status != "approved":
        fail(f"cannot submit experiment {exp_id} from status {status!r}")

    submission = cs(
        f"/goals/{GOAL_ID}/experiments/{exp_id}/submit",
        method="POST",
        body={"approver": RUNNER_ID, "credentialed": True},
        timeout=180,
    )
    run_request_id = submission["runs"][0]["run_request_id"]
    print(f"experiment_id={exp_id}")
    print(f"run_request_id={run_request_id}")

    record = repro(f"/api/v1/run-requests/{run_request_id}", timeout=30)
    callback = (record.get("request") or {}).get("callback") or {}
    if callback.get("url") != f"{CS}/result-bundles":
        fail(f"unexpected callback URL: {callback.get('url')!r}")

    for i in range(1, int(os.environ["AUTORUN_MAX_WORKER_JOBS"]) + 1):
        record = repro(f"/api/v1/run-requests/{run_request_id}", timeout=30)
        state = record.get("state")
        print(f"repro_state_before_worker={state}")
        if state in TERMINAL_REPRO_STATES:
            break
        run_worker_once(i)
    record = repro(f"/api/v1/run-requests/{run_request_id}", timeout=30)
    if record.get("state") != "completed":
        fail(f"repro run did not complete; final state={record.get('state')!r}")
    events = repro(f"/api/v1/runs/{run_request_id}/events", timeout=30)
    if "callback_delivered" not in [event.get("event_type") for event in events]:
        fail("repro did not record callback_delivered")

    deadline = time.monotonic() + float(os.environ["AUTORUN_CALLBACK_TIMEOUT"])
    while time.monotonic() < deadline:
        bundles = cs(f"/experiments/{exp_id}/result-bundles", timeout=30)
        agg = cs(f"/experiments/{exp_id}/validation-aggregation", timeout=30)
        rr = cs(f"/run-requests/{run_request_id}", timeout=30)
        if bundles.get("total", 0) and rr.get("status") == "completed":
            if agg.get("aggregate_status") != "passed":
                fail("aggregation is not passed: " + json.dumps(agg, indent=2))
            break
        time.sleep(2)
    else:
        fail("callback ResultBundle was not ingested before timeout")

    health = cs(f"/goals/{GOAL_ID}/evaluation/callback-health", timeout=30)
    if run_request_id in set(health.get("missing_run_request_ids") or []):
        fail("callback-health reports this run as missing")
    if ARCHIVE_SUCCESS:
        transition_experiment(exp_id, "archived")
    return exp_id, run_request_id


def main() -> None:
    log("checking APIs")
    goal = cs(f"/goals/{GOAL_ID}")
    repro("/api/v1/workspaces", timeout=30)
    if not EXPERIMENT_REPO.is_dir() or not EXP_RUNNER.is_file():
        fail("experiment runner repo or exp-runner executable not found")
    plan_summary()
    if not EXECUTE:
        log("plan-only mode; pass --execute to mutate state and run a worker")
        return

    backup = backup_db()
    log(f"database backup: {backup}")

    log("deriving goal-scoped taxonomy")
    taxonomy = cs(
        f"/ontology/derive{qs({'goal_id': GOAL_ID})}",
        method="POST",
        body={"top_k": TOP_K, "max_families": MAX_FAMILIES, "dry_run": False},
        timeout=240,
    )
    print(f"taxonomy_families={len(taxonomy.get('families') or [])}")

    log("running scout")
    scout_body: dict[str, Any] = {"top_k": TOP_K, "synthesize": SYNTHESIZE}
    if METHOD_FAMILY:
        scout_body["method_families"] = [METHOD_FAMILY]
    scout = cs(f"/goals/{GOAL_ID}/scout", method="POST", body=scout_body, timeout=900)
    print(f"scout_run_id={scout.get('scout_run_id')} evidence={scout.get('evidence_count')}")

    log("generating approaches deterministically from evidence")
    approach_body: dict[str, Any] = {
        "scout_run_id": scout.get("scout_run_id"),
        "min_evidence_count": MIN_EVIDENCE,
    }
    if METHOD_FAMILY:
        approach_body["method_families"] = [METHOD_FAMILY]
    approach_gen = cs(f"/goals/{GOAL_ID}/approaches/generate", method="POST", body=approach_body)
    print(f"approaches_created={approach_gen.get('approaches_created')} skipped={approach_gen.get('approaches_skipped_duplicate')}")
    review_generated_approaches()

    log("scoring approaches")
    scores = cs(f"/goals/{GOAL_ID}/approaches/score-all", method="POST", body={"weight_profile": "default"})
    print(f"scores={len(scores)}")

    log("generating and reviewing hypotheses")
    hyp_gen = cs(
        f"/goals/{GOAL_ID}/hypotheses/generate",
        method="POST",
        body={"max_hypotheses": MAX_HYPOTHESES, "include_exploratory": True},
    )
    print(f"hypotheses_created={hyp_gen.get('hypotheses_created')} skipped={hyp_gen.get('hypotheses_skipped_duplicate')}")
    review_generated_hypotheses()

    log("generating experiments")
    exp_gen = cs(
        f"/goals/{GOAL_ID}/experiments/generate",
        method="POST",
        body={"max_experiments": MAX_EXPERIMENTS},
    )
    print(f"experiments_created={exp_gen.get('experiments_created')} skipped={exp_gen.get('experiments_skipped_duplicate')}")

    log("selecting runnable experiment")
    exp, preflight = choose_runnable_experiment()
    print(f"selected_experiment={exp['id']} selected_reproduction={preflight.get('selected_reproduction_id')}")
    exp_id, run_id = submit_and_execute(exp)
    log("autonomous goal rerun passed")
    print("summary=" + json.dumps(
        {
            "goal_id": GOAL_ID,
            "goal_name": goal["name"],
            "experiment_id": exp_id,
            "run_request_id": run_id,
            "method_filter": METHOD_FAMILY,
        },
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
PY
