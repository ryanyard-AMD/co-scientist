# Execution Callback Verification

Date: 2026-08-09

This records a live verification of the co-scientist -> repro -> co-scientist
return leg after callback dispatch was added to repro.

## Repeatable Smoke Command

Use the smoke script to repeat the callback handoff check against any reviewed or
approved source experiment:

```bash
scripts/verify-callback-handoff.sh <GOAL_ID> <SOURCE_EXPERIMENT_ID>
```

For the SFANC callback path used during this verification:

```bash
scripts/verify-callback-handoff.sh \
  a741ab57-5f05-45c4-9297-07cc07aabc64 \
  a538fad1-e186-47b9-8ffe-99492233a305
```

Prerequisites:

- co-scientist API running at `CS_API_BASE` (default
  `http://localhost:8001/co-scientist`);
- repro API running at `REPRO_API_BASE` (default `http://localhost:8003`);
- callback URL reachable from repro, normally via
  `CS_PUBLIC_BASE_URL=http://localhost:8001`;
- experiment runner repo at `EXPERIMENT_REPO` (default `/home/ryard/experiment`);
- `exp-runner` available at `EXP_RUNNER` (default
  `/home/ryard/experiment/.venv/bin/exp-runner`);
- retrieval service available if repro preflight needs method recommendation.

The script duplicates the source experiment, sets the duplicate's
`experiment_control_plane`, runs preflight, reviews/approves/submits it, runs
worker iterations until the new RunRequest reaches a terminal state, and asserts:

- repro completed the run;
- repro recorded `callback_delivered`;
- co-scientist ingested a ResultBundle for the new experiment;
- co-scientist aggregation is `passed`;
- `cs eval callback-health` passes for the goal.

By default the duplicate remains in the database as an audit record. Set
`SMOKE_ARCHIVE_ON_SUCCESS=1` to archive it after a successful smoke run.

## Smoke Script Verification

Date: 2026-08-10

The smoke script was run against the canonical SFANC experiment:

```bash
scripts/verify-callback-handoff.sh \
  a741ab57-5f05-45c4-9297-07cc07aabc64 \
  a538fad1-e186-47b9-8ffe-99492233a305
```

Result:

- Verification duplicate: `0fcad538-27ee-437a-90a8-bd2c96f9fbea`
- RunRequest: `run-f8f7c5515385`
- Repro state: `completed`
- Co-scientist ResultBundle count: `1`
- Co-scientist aggregation: `passed`
- Callback-health rate: `1.0`

The ResultBundle was received through the automatic callback path; no manual
ResultBundle POST was performed.

## Setup

- Goal: `a741ab57-5f05-45c4-9297-07cc07aabc64`
- Source experiment: `f4e62d90-20a9-4ef9-b817-5b0cfbb557e5`
- Verification experiment duplicate: `a538fad1-e186-47b9-8ffe-99492233a305`
- Control plane: `http://localhost:8003`
- Callback URL: `http://localhost:8001/co-scientist/result-bundles`
- Worker: `exp-runner worker --runner-id cosci-callback-e2e --runtime python-numerics --label python_numerics --max-concurrent 1 --runs-root runs --max-iterations 1`

## Result

- RunRequest: `run-8afa3180d10a`
- Repro state: `completed`
- Repro validation status: `passed`
- Repro raw event store includes `callback_delivered` for terminal event
  `run_completed`.
- Co-scientist ResultBundle: `rb-run-8afa3180d10a-att-32aab4f5d928`
- Co-scientist RunRequest status: `completed`
- Co-scientist validation aggregation: `passed`
  - total runs: `1`
  - passed runs: `1`
  - failed runs: `0`
  - missing runs: `0`

No manual ResultBundle POST was performed for this verification run. The bundle
arrived through the repro callback path.

## Notes

The long-running repro API process may need a restart after deploying the
callback-dispatch code before its typed `/events` response includes the new
`callback_delivered` enum value. The raw event store did contain the event during
this verification.

## Metric Alias Verification

Date: 2026-08-09

After repro exposed `SpecDescriptor.metric_aliases` through
`/api/v1/handoffs/preview`, co-scientist preflight was rerun against the canonical
SFANC experiment:

- Experiment: `a538fad1-e186-47b9-8ffe-99492233a305`
- Selected reproduction: `meta-learning-sfanc-maml-fxlms-v1`
- Preflight status: `runnable: true`
- Blocking reasons: `[]`
- `metric_contract.preview.metric_aliases` contained the SFANC native→canonical
  aliases for `noise_reduction`, convergence speedup, and case-2 convergence.
- The prior `used local metric map fallback` warning was absent.

Remaining preflight warnings were expected scientific-contract warnings: this
SFANC reproduction does not emit `filter_selection_accuracy`,
`quiet_zone_radius`, `filter_switch_latency`, or `processing_latency`, so those
pass conditions remain unmeasurable for this reproduction.
