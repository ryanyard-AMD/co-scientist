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

Preflight now sends the first expanded `co_scientist.run_request.v1` payload to
repro's `POST /api/v1/handoffs/preview` endpoint. Repro normalizes that payload
into its `ExperimentProposal`, selects or recommends a curated reproduction,
designs the grounded spec, and returns honored/dropped variables plus warnings
without queueing a run. The older `recommend-method` / `metrics-surface`
sequence remains as a compatibility fallback for repro deployments that do not
yet expose `/handoffs/preview`.

The response reports:

- whether the experiment is runnable;
- blocking reasons and warnings;
- the selected repro reproduction and workspace;
- the card method family and candidate method families;
- canonical pass conditions;
- unmeasurable pass-condition metrics;
- the repro metric contract and local native-to-canonical fallback map;
- the design-run payload that would be sent downstream.
- the repro preview report's honored/dropped variables and selection warnings
  when available.

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
  canonical pass conditions, runtime, expected artifacts, and the card's
  `method_family`;
- `run`: per-run sweep parameters, run index, run count, and initial status;
- `approval_policy` and `resource_policy`;
- `result_contract`: the ResultBundle endpoint, required correlation fields,
  expected metrics/artifacts, and pass conditions.

`result_contract.result_bundle_endpoint` is an absolute URL derived from
`CS_PUBLIC_BASE_URL` plus `CS_API_PREFIX` (default
`http://localhost:8001/co-scientist/result-bundles`). Configure
`CS_PUBLIC_BASE_URL` to the address the Experimentation System can reach.

The downstream system should reject the RunRequest up front when it cannot honor
this contract. Completed runs should report through ResultBundle ingestion using
the IDs in `result_contract.required_correlation`.

`experiment.method_family` biases repro's choice of reproduction. Preflight and
submission must send the same value: without it repro re-ranks by objective and
hypothesis text alone and can select a different reproduction than the one
preflight cleared, so a clean preflight is followed by a `409` on submit. Both
payload builders resolve it from the card's single approach; combination cards
(more than one approach) send no hint, matching `runner._primary_approach`.

When `experiment_control_plane` is set on the card, preflight and submission both
call that same repro control-plane URI. The default submitter sends this payload
to repro's `POST /api/v1/handoffs/run` endpoint and stores the returned
control-plane `run_id` as the co-scientist `RunRequestReference`. When no
control-plane URI is configured, preflight uses `CS_REPRO_URL` and submission
preserves the local generated-ID stand-in used for offline development and tests.

## Return Leg

Repro stores `result_contract.result_bundle_endpoint` as the control-plane
`RunRequest.callback.url`. When a worker ingests a terminal ResultBundle, repro
POSTs a co-scientist-compatible payload to that callback URL. Co-scientist ingests
the callback through `POST /co-scientist/result-bundles`, reconciles it to the
stored `RunRequestReference`, updates run and experiment execution status, and
recomputes validation aggregation.

Callback delivery is best-effort on the repro side: if the POST fails, repro
records a `callback_failed` event while preserving the runner result. Operators
can still recover by fetching repro's completion/failure surface and posting the
bundle to `/co-scientist/result-bundles` manually. Queued runs require a repro
worker (`exp-runner worker`) to be running; the repro API server queues work but
does not execute it itself.

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
