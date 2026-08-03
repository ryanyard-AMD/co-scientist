# Logical Flaw Remediation

This document tracks the implementation steps for the logic review findings and
the tests that guard each fix.

## Step 1: Hypothesis LLM Fallback

Problem:

- Hypothesis generation promised deterministic synthesis when no Anthropic key
  is available, but a locally configured invalid key forced tests and normal
  generation through the LLM path.
- The test harness loaded `.env`, so local credentials could change unit-test
  behavior.

Fix:

- Tests now force `CS_HYPOTHESIS_USE_LLM=false` before importing the application.
- Hypothesis generation catches Anthropic API failures and logs a governance
  entry before falling back to deterministic synthesis.

Coverage:

- `tests/test_hypothesis_api.py`
- `tests/test_hypothesis_service.py`

## Step 2: Goal-Scoped Nested Resources

Problem:

- Several routes were nested under `/goals/{goal_id}` but fetched or mutated
  resources by object ID only.
- A caller that knew an approach, hypothesis, or experiment ID could access it
  through the wrong goal path.
- Experiment creation validated approach ownership but did not validate that a
  supplied hypothesis belonged to the same workspace.

Fix:

- Approach, hypothesis, experiment, score, handoff-list, and evidence-label
  service calls now accept optional `goal_id` scope and return `404` on
  workspace mismatch.
- Goal-nested routers pass `goal_id` into those service calls.
- Experiment creation rejects cross-workspace hypothesis links.

Coverage:

- `tests/test_approach_api.py`
- `tests/test_hypothesis_api.py`
- `tests/test_experiment_api.py`
- `tests/test_score_api.py`

## Step 3: Atomic ResultBundle Ingestion and Correlation Checks

Problem:

- ResultBundle ingestion synced RunRequest status through helpers that committed
  before score, device, and roadmap side effects completed.
- A later failure could leave a bundle/run status persisted without the
  corresponding downstream updates.
- Incoming bundle payloads could name a RunRequest or approach IDs that were not
  correlated with the target Experiment Card.

Fix:

- Execution status, RunRequest status, and batch recomputation helpers can now
  participate in caller-owned transactions.
- ResultBundle ingestion applies run status sync with `commit=False` and commits
  only after aggregation, scoring, approach/device refresh, and roadmap refresh
  complete.
- ResultBundle ingestion rejects RunRequests, batches, and explicit
  `approach_ids` that do not match the target experiment/workspace.

Coverage:

- `tests/test_result_bundle.py`
- `tests/test_execution_service.py`
- `tests/test_approval_api.py`
