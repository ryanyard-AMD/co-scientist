# Execution Callback Verification

Date: 2026-08-09

This records a live verification of the co-scientist -> repro -> co-scientist
return leg after callback dispatch was added to repro.

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
