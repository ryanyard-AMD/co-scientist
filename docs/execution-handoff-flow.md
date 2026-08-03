# Execution Handoff Flow

The production execution path should be:

1. Create and review an `ExperimentCard`.
2. Run execution preflight to resolve the repro execution plan.
3. Approve the experiment.
4. Submit one or more RunRequests to the Experimentation/Repro system.
5. Ingest status updates and ResultBundles.
6. Let validation aggregation drive approach, score, device, and roadmap updates.

## Execution Preflight

`POST /co-scientist/goals/{goal_id}/experiments/{experiment_id}/preflight`
resolves the contract between co-scientist and repro without submitting or
running anything.

The response reports:

- whether the experiment is runnable;
- blocking reasons and warnings;
- the selected repro reproduction and workspace;
- the card method family and candidate method families;
- canonical pass conditions;
- unmeasurable pass-condition metrics;
- the repro metric contract and local native-to-canonical fallback map;
- the design-run payload that would be sent downstream.

Use preflight before approval/submission. A failed preflight should block normal
submission unless a human explicitly accepts the risk and records the reason.

## Current Transition State

The direct `experiment run` path still exists for compatibility and developer
testing. It now creates co-scientist execution references and emits a
ResultBundle through the same ingestion service used by external handoff
completions. The intended production path remains RunRequest handoff followed by
ResultBundle ingestion from the external system.

## RunRequest Contract

Submission sends each downstream run as `schema: co_scientist.run_request.v1`.
The payload includes:

- `co_scientist`: experiment, goal, workspace, batch, correlation, hypothesis,
  and approach IDs;
- `experiment`: objective, hypothesis, baselines, assumptions, metrics,
  canonical pass conditions, runtime, and expected artifacts;
- `run`: per-run sweep parameters, run index, run count, and initial status;
- `approval_policy` and `resource_policy`;
- `result_contract`: the ResultBundle endpoint, required correlation fields,
  expected metrics/artifacts, and pass conditions.

The downstream system should reject the RunRequest up front when it cannot honor
this contract. Completed runs should report through ResultBundle ingestion using
the IDs in `result_contract.required_correlation`.

## Direct Runner Compatibility

The direct repro runner is a compatibility adapter, not the target production
executor. When it completes a run, it now:

1. creates an `ExecutionBatchReference`;
2. registers a `RunRequestReference` for the repro run ID;
3. derives a deterministic bundle status from measured metrics and pass
   conditions;
4. ingests a `ResultBundle`;
5. transitions the legacy experiment card status from `running` to
   `completed`, `failed`, or `inconclusive`.

This keeps score updates, approach execution evidence, device evidence, and
roadmap refreshes on the canonical ResultBundle path even during local/direct
execution.
