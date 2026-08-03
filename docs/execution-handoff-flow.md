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
testing. The intended production path is RunRequest handoff followed by
ResultBundle ingestion.
