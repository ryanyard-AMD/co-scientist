# Co-scientist Integration Guide — Handoff P4 (Hypothesis → Method Recommendation)

This is the **client-side** guide for the co-scientist team. It describes what changed in
the repro handoff surface for P4 and exactly how to call it. For the repro-internal design
rationale see [`f-coscientist-handoff-p4.md`](f-coscientist-handoff-p4.md); for the P1–P3
handoff see [`e-coscientist-handoff-p1-p3.md`](e-coscientist-handoff-p1-p3.md).

## What P4 changes for you

Previously (P1–P3) the co-scientist had to *know* which reproduction to run: you sent an
`experiment_id` (or a paper the workspace was already bound to) and repro grounded the
command. The original P4 request flagged the failure mode this creates — two VAST cards (one
for acoustic contrast control, one for pressure matching) came back with **identical
metrics** because the *method* never crossed the handoff.

P4 closes the gap the other way. You now hand over a **hypothesis** and repro:

1. queries the retrieval system with it,
2. returns **ranked candidate methods** (papers), each flagged **runnable** (has a
   registered reproduction) or not, and
3. auto-drafts the top runnable candidate into a grounded spec — **without running it**.

Repro does *not* auto-pick a single method. You get the ranked list and decide; the draft is
a convenience for the top runnable hit. To actually execute, you call the existing
`design-run` (P3) separately.

Your side needs to implement three things: (a) call `recommend-method` with a hypothesis,
(b) present/act on the ranked candidates, and (c) optionally read `metrics-surface` to show
what each candidate reproduction actually measures.

## New endpoints

Both are additive; nothing in the P1–P3 surface changed shape. Auth is unchanged — send
`X-Api-Key` when `REPRO_API_KEY` is set on the repro service.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/workspaces/{id}/recommend-method` | Rank candidate methods for a hypothesis; draft the top runnable one |
| `GET`  | `/api/v1/workspaces/{id}/metrics-surface` | List which metrics each registered reproduction of the workspace paper validates |

### 1. `POST /api/v1/workspaces/{id}/recommend-method`

**Query params**

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `top_k` | int | `10` | How many retrieval hits to consider before dedup. |
| `draft` | bool | `true` | When `true`, ground + persist a draft for the top runnable candidate. Set `false` to get candidates only. |

**Request body** — an `ExperimentProposal`. Only `hypothesis` is really needed; everything
else is optional and refines the result.

```jsonc
{
  "hypothesis": "reduce sound leakage into the dark zone in a reverberant room",
  "objective": "sound zone control",              // optional; appended to the query if present
  "method_family": "pressure_matching",           // optional bias hint (see vocabulary below)
  "independent_variables": { "t60": 0.5, "speaker_count": 24 },  // optional; used when drafting
  "experiment_id": null                            // optional; disambiguates a multi-variant paper
}
```

Key semantics:

- **`hypothesis` drives retrieval.** It is the query. If absent, `objective` is used as the
  fallback query text.
- **`method_family` is a *bias*, not a filter.** When set, candidates whose paper implements
  that family are stably boosted to the top of the ranking — but non-matching and
  unreproduced hits are still returned. It never removes results. It also sets
  `method_family_supported` on the drafted spec so two proposals that differ *only* by
  `method_family` produce distinguishable drafts (this is the fix for the identical-metrics
  problem).
- **`independent_variables`** are only consumed if a draft is produced — they are ground onto
  the reproduction's real CLI flags exactly as in P1–P3 (honored/dropped reporting applies).

**Response** — `200` with a `RecommendationResult`:

```jsonc
{
  "hypothesis": "reduce sound leakage ... pressure matching",  // the composed query text
  "candidates": [
    {
      "paper_id": "786380fd-...",
      "title": "Fast Generation of Sound Zones Using Variable Span Trade-off",
      "score": 0.91,
      "rationale": "Method",                 // top chunk's section title / snippet
      "runnable": true,                      // has a registered reproduction
      "experiment_ids": ["fast-generation-of-sound-zones-using-var-v1"],
      "method_families": ["variable_span_tradeoff", "acoustic_contrast_control",
                          "pressure_matching", "sound_zone_control"],
      "family_match": true,                  // matched your method_family bias
      "capability_matched": true             // (P5) surfaced by declared capability, not paper text
    },
    {
      "paper_id": "unreproduced-paper-uuid",
      "title": "Some related paper we have not reproduced",
      "score": 0.63,
      "rationale": "Introduction",
      "runnable": false,                     // surfaced, but no registered reproduction
      "experiment_ids": [],
      "method_families": [],
      "family_match": false,
      "capability_matched": false
    }
  ],
  "retrieval_degraded": false,               // (P5) true if retrieval failed and candidates come from the capability set alone
  "draft_id": "a1b2c3d4-...",                 // null when draft=false or no runnable candidate
  "drafted_experiment_id": "fast-generation-of-sound-zones-using-var-v1",  // null likewise
  "honored":  [ { "proposal_name": "t60", "canonical": "reverb_t60_s",
                  "flag": "--t60", "value": 0.5, "kind": "scalar" } ],
  "dropped":  [ { "proposal_name": "speaker_count", "reason": "unsupported" } ],
  "method_family_supported": true            // null when no method_family declared
}
```

Notes for your implementation:

- **No run is submitted.** There is deliberately **no `run_id`** in this response. The
  `draft_id` points at a persisted, audit-able draft (fetch it via `GET /api/v1/drafts/{id}`).
- **Candidates are deduped by `paper_id`** in retrieval order, keeping each paper's best
  chunk score. Use `runnable` to decide what you can actually execute now, and
  `experiment_ids` to pick a specific variant.
- **`honored`/`dropped`/`method_family_supported`/`drafted_experiment_id`** describe *the
  drafted candidate only*. They are empty/null if no draft was produced.

### Capability-aware ranking (P5)

Ranking used to be driven purely by how well a **paper's text** matched your hypothesis, so a
runnable reproduction was invisible to a card about a method its *source paper* wasn't
textually about — an `acoustic_contrast_control` card never reached VAST even though VAST
declares it. That's fixed:

- **Set `method_family` and a runnable reproduction that declares it is guaranteed to appear.**
  When you pass `method_family`, every runnable reproduction whose declared `method_families`
  cover it is included as a candidate (`runnable: true`) even if retrieval didn't surface its
  paper — flagged `capability_matched: true`. So an ACC proposal returns VAST as a runnable
  candidate **without your hypothesis naming VAST's paper**. You can select and run it from
  `recommend-method` alone; no `metrics-surface` walk or client-side registry needed.
- **Ranking order:** retrieval-*and*-capability matches first, then capability-only appends,
  then everything else. `capability_matched` distinguishes a registry-sourced candidate from a
  text-retrieved one.
- **Honest "no runnable" is preserved.** If **no** reproduction declares the requested family,
  nothing runnable is appended — capability matching never fabricates runnability. Your
  runner's refuse-with-422 path still holds for genuinely unsupported methods.
- **`retrieval_degraded`:** if retrieval is momentarily unavailable but your `method_family`
  has a capability set, you still get that runnable set with `retrieval_degraded: true` instead
  of a 502. A true outage with no usable `method_family` still returns 502 (retry with backoff).
- **Full proposal body now accepted.** Sending the whole `ExperimentProposal` (long
  `hypothesis` + `independent_variables`/`metrics`/`pass_conditions`) no longer 502s — the
  query is length-capped server-side. A recommendation still only *needs* `hypothesis`
  (+ optional `method_family`), but the full body is safe to send.

**Errors**

| Status | When |
|--------|------|
| `404` | Workspace `{id}` not found. |
| `502` | Retrieval system unavailable (`detail: "retrieval unavailable: ..."`). Retrieval always runs, so a retrieval outage fails the whole call — retry with backoff. |

### 2. `GET /api/v1/workspaces/{id}/metrics-surface`

Read-only. Answers "if I reproduce this paper, what will actually be measured?" — so you can
show a co-scientist the emitted-metric surface *before* committing to a run. Derived from the
curated ground-truth spec, so it never drifts from what the reproduction really validates.

**Response** — `200`:

```jsonc
{
  "paper_id": "36839934-...",
  "reproductions": [
    {
      "experiment_id": "physics-informed-ml-sound-field-estimation-fig8-pinn-v1",
      "method_families": ["sound_field_estimation", "physics_informed_neural_network"],
      "metrics": ["nmse_dB", "..."]
    }
    // one entry per registered reproduction of the paper (a paper may map to several variants)
  ]
}
```

`reproductions` is an **empty list** (still HTTP `200`, not `404`) when the workspace paper
has no registered reproduction. `404` only if the workspace itself is missing.

## Recommended client workflow

```
1. Create/resolve a workspace bound to the paper of interest (existing P1 flow).
2. POST /recommend-method  { "hypothesis": "...", "method_family": "..." (optional) }
3. Show `candidates`:
     - runnable=true  → offer "run this"; experiment_ids gives the exact variant(s)
     - runnable=false → surface as a reference/reading, not executable
4. (optional) GET /metrics-surface to show what each runnable candidate measures.
5. To execute the chosen method: POST /workspaces/{id}/design-run   (existing P3 endpoint)
     with an ExperimentProposal carrying the chosen `experiment_id` +
     `independent_variables`. This is the step that actually submits a run and returns a run_id.
```

The draft produced by step 2 is a convenience/audit artifact for the top runnable candidate;
you are free to ignore it and drive `design-run` with a different candidate you picked from
the list.

## Method-family vocabulary (`method_family`)

`method_family` is optional and matched case/space/dash-insensitively — `"Acoustic Contrast
Control"`, `"acoustic-contrast-control"`, and `"acoustic_contrast_control"` are equivalent.
Canonical families currently recognized:

```
variable_span_tradeoff        acoustic_contrast_control     pressure_matching
robust_pressure_matching      sound_zone_control            parametric_array_modeling
sound_field_estimation        sound_field_reconstruction    spatial_covariance_estimation
kernel_interpolation          adaptive_kernel_interpolation physics_informed_neural_network
boundary_integral             dictionary_learning           physics_informed
```

Which registered reproduction implements which families (this is what `family_match` and the
`recommend-method` bias key off):

| experiment_id | method_families |
|---------------|-----------------|
| VAST | variable_span_tradeoff, acoustic_contrast_control, pressure_matching, sound_zone_control |
| CGMM | robust_pressure_matching, pressure_matching, sound_zone_control |
| PAL | parametric_array_modeling |
| PIML Fig4 (kernel) | sound_field_estimation, kernel_interpolation |
| PIML Fig8 (PINN) | sound_field_estimation, physics_informed_neural_network |
| PIML Fig8 (adaptive) | sound_field_estimation, adaptive_kernel_interpolation |
| PIBI | sound_field_reconstruction, boundary_integral, physics_informed_neural_network |
| PIDL | sound_field_reconstruction, dictionary_learning, physics_informed |
| KRR (CIKRR) | spatial_covariance_estimation, kernel_interpolation, sound_zone_control |

Passing a family that no reproduction implements is fine — it simply yields no boost and
`method_family_supported: false` on any draft (advisory, never blocks).

## How the original P4a/b/c requests map to what shipped

| Original request | Shipped as |
|------------------|------------|
| **P4a** — structured `method_family` on the proposal | `ExperimentProposal.method_family`, repurposed as a *bias hint* into retrieval ranking (not the source of truth). |
| **P4b** — method-aware descriptors | Each reproduction declares `method_families`; drives `family_match`, ranking bias, and the `method_family_supported` compatibility flag. |
| **P4c** — emitted-metric surface | `GET /metrics-surface`. |

The one intentional reframe: rather than the co-scientist *declaring* the method, repro
*recommends* it from the hypothesis via retrieval. `method_family` remains available as a hint
for teams that already know the method they want.

## cURL quick reference

```bash
# Recommend + auto-draft the top runnable candidate
curl -s -X POST "$REPRO/api/v1/workspaces/$WS/recommend-method" \
  -H 'content-type: application/json' -H "X-Api-Key: $KEY" \
  -d '{"hypothesis":"pressure matching in reverberant rooms","method_family":"robust_pressure_matching"}'

# Candidates only, wider net, no draft
curl -s -X POST "$REPRO/api/v1/workspaces/$WS/recommend-method?draft=false&top_k=20" \
  -H 'content-type: application/json' -H "X-Api-Key: $KEY" \
  -d '{"hypothesis":"estimate a sound field from sparse microphones"}'

# What does each reproduction of this paper measure?
curl -s "$REPRO/api/v1/workspaces/$WS/metrics-surface" -H "X-Api-Key: $KEY"
```

CLI equivalents (for local testing against the same logic):

```
repro workspace recommend-method <ws-id> --proposal <json|file> [--top-k N] [--no-draft] [--json]
repro workspace metrics-surface  <ws-id> [--json]
```
