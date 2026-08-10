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

## Autonomous Goal Rerun Command

For a broader goal-level pipeline, use:

```bash
scripts/autonomous-goal-rerun.sh [--execute] [--method METHOD] <GOAL_ID>
```

Default mode is plan-only. It checks the co-scientist and repro APIs and prints
the current counts for approaches, hypotheses, experiments, and callback health.

`--execute` mutates state. It:

1. creates a SQLite backup with the online-backup API;
2. derives/persists the goal taxonomy, using deterministic fallback if the LLM is
   unavailable;
3. runs scout retrieval;
4. generates deterministic approach cards from evidence and reviews generated
   cards;
5. scores approaches;
6. generates and reviews hypotheses;
7. generates experiments;
8. picks the first non-submitted experiment whose preflight is runnable, or
   duplicates the best current experiment if generation produced only duplicates;
9. approves/submits it to repro;
10. runs local `exp-runner worker` iterations;
11. asserts repro completion, `callback_delivered`, co-scientist ResultBundle
    ingestion, passed aggregation, and callback-health success.

Use `--method selective_fixed_filter_anc` to constrain the rerun to the SFANC
method family. Set `AUTORUN_ARCHIVE_SUCCESS=1` to archive the selected
verification experiment after success.

## Autonomous Goal Rerun Verification

Date: 2026-08-10

The autonomous goal rerun script was run with the SFANC method filter and
archive-on-success:

```bash
AUTORUN_TOP_K=5 \
AUTORUN_MAX_FAMILIES=8 \
AUTORUN_ARCHIVE_SUCCESS=1 \
scripts/autonomous-goal-rerun.sh \
  --execute \
  --method selective_fixed_filter_anc \
  a741ab57-5f05-45c4-9297-07cc07aabc64
```

Result:

- Taxonomy derivation completed with `8` families using the deterministic fallback
  path as needed.
- Scout run: `71d33777-4b63-452e-908d-43158cd0eddd`
- Evidence records: `90`
- Selected verification experiment: `8137a832-628a-49e1-bdbd-0a0f83858065`
- RunRequest: `run-4d6ddf9700fe`
- Repro state: `completed`
- Co-scientist ResultBundle: `rb-run-4d6ddf9700fe-att-891a5c9a910d`
- Co-scientist aggregation: `passed`
  - total runs: `1`
  - passed runs: `1`
  - missing runs: `0`
- Callback health after the run: `100% PASS`
- The verification experiment was archived after success.

The script created `coscientist.db.bak.autorun.20260810_005345` before mutating
state. The backup command reported an existing SQLite integrity warning
(`NULL value in device_concept_cards.confidence`) but continued, matching the
project backup script's warning-only behavior.

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
