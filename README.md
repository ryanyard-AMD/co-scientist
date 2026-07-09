# Co-Scientist: Agent-Based Research-to-Device Synthesis

An agent-based co-scientist system that accelerates research-to-device synthesis for personal sound zones. Sits above the [Research Paper Knowledge Retrieval System](https://github.com/ryanyard-AMD/retrieval) and [Reproducible Research Experimentation Environment](https://github.com/ryanyard-AMD/experiment) to convert literature into structured approach candidates, score them, generate experiments, and propose device architectures.

## Architecture

```
Layer 4: Co-Scientist (this project, port 8001)
         ├── Goal Workspace        (CS-EPIC-GOAL)
         ├── Research Scout        (CS-EPIC-SCOUT)
         ├── Approach Forge        (CS-EPIC-APPROACH)
         ├── Approach Critic       (CS-EPIC-CRITIC)
         ├── Rubric Scoring        (CS-EPIC-SCORE)
         ├── Hypothesis Gen        (CS-EPIC-HYPOTHESIS)
         ├── Experiment Design     (CS-EPIC-EXPERIMENT)
         ├── Human Approval        (CS-EPIC-APPROVAL)
         ├── Execution Tracking    (CS-EPIC-EXECUTION)
         ├── Experiment Validation (CS-EPIC-VALIDATION)
         ├── Device Synthesis      (CS-EPIC-DEVICE)
         ├── Research Roadmap      (CS-EPIC-ROADMAP)
         ├── Agent Governance      (CS-EPIC-GOVERNANCE)
         ├── Web UI                (CS-EPIC-UI)
         └── Evaluation Metrics    (CS-EPIC-EVALUATION)
              │
Layer 2: ├── Retrieval API (port 8000) — Neo4j knowledge graph, vector search
         └── Experiment Runner — containerized execution, MLflow tracking
```

## Implemented Epics

### CS-EPIC-GOAL: Applied Research Goal Workspace

The foundational object that organizes all downstream artifacts around a single applied research objective.

- **ResearchGoal** with status lifecycle: `draft` → `active` → `archived`
- Success criteria (metric, operator, target, unit) and device constraints
- `workspace_id` join key for all downstream epics

### CS-EPIC-SCOUT: Research Scout and Evidence Retrieval

Evidence retrieval layer that queries the retrieval API and organizes literature evidence for a research goal.

- Decomposes goals into search queries across method families, metrics, and constraints
- Groups evidence by method family, metric, hardware assumption, and failure mode
- Classifies chunks using DB-backed ontology terms (falls back to hardcoded dicts if DB empty)
- Detects insufficient evidence with configurable thresholds and suggests related methods
- Distinguishes primary vs. incidental method mentions
- Full traceability: every evidence record links to paper, section, page, chunk, and source
- **Quality gate** — keeps the synthesis agent from manufacturing prose around non-evidence:
  - *Substantive filter* flags (does not delete) bare section headers, numbered sub-headings, and reference/bibliography lines as `is_substantive=False` (configurable via `CS_SCOUT_MIN_CHUNK_WORDS`); flagged records are persisted for audit but excluded from synthesis input and strength counting
  - *Score floor* (`CS_SCOUT_MIN_SCORE`, default `0.0`) drops the retrieval server's graph-expansion neighbor chunks that arrive at `score: 0.0`
  - *Near-duplicate dedup* collapses identical chunk text within a paper (in addition to `chunk_id` dedup), so a repeated header can no longer triple a method family's apparent support
  - *Substantive-weighted strength*: evidence strength is computed from distinct papers with a **substantive** record, not raw paper count, so header-only families read `none`/`weak` rather than `strong`
- **Artifact evidence** (`CS_SCOUT_INCLUDE_ARTIFACTS`, default on): extracted tables/figures with their Claude-written summaries are ingested as `record_kind="artifact"` evidence records and flow through the same method-family grouping and synthesis — surfacing quantitative measured results alongside prose chunks
- **Claim evidence** (`CS_SCOUT_USE_CLAIMS`, default on; `CS_SCOUT_CLAIMS_TOP_K`, default 25): the retrieval system's GraphRAG claim graph is consumed as first-class evidence. Per method family, Scout calls the retrieval `POST /claims/search` endpoint and ingests the returned typed claims (`finding`/`hypothesis`/`contribution`/`limitation`) as `record_kind="claim"` records, each carrying `claim_type`, `confidence`, the grounding `chunk_id`, the upstream `source_claim_id`, and its `SUPPORTS`/`CONTRADICTS`/`EXTENDS` edges (`claim_relationships`). Claims are pre-grounded findings extracted upstream, so this replaces asking the synthesis agent to re-derive them from raw prose — and surfaces cross-paper contradictions the per-family synthesis cannot compute on its own.
- **Entity-grounded classification** (`CS_SCOUT_USE_ENTITIES`, default on): after evidence is gathered, Scout fetches each contributing paper's Method/Metric entity nodes (`GET /entities/papers/{id}`) and maps their curated names into the canonical taxonomy via the same keyword classifier, then unions the result into every record's `method_families` and `metric_names`. This catches a paper's methods and measured metrics even when a given chunk's prose never restates them (e.g. a results chunk that reports numbers without renaming the technique). Purely additive over the per-chunk keyword classification — a keyword match is never dropped, entity names that map to no canonical term are ignored, and papers without entity nodes fall back to keyword classification only.
- **Optional Claude synthesis** (`--synthesize`): per method family, a Claude agent reads the retrieved chunks **and the extracted claims** and produces a grounded synthesis (narrative, key findings, reported metrics, hardware requirements, failure modes, open questions). Claims are surfaced to the agent distinctly with their type, confidence, and relationship edges — `finding`/`contribution` claims feed key findings, `limitation` claims and `CONTRADICTS` edges feed failure modes, and `hypothesis` claims plus unresolved contradictions feed open questions. Pure RAG — the agent may cite only the `evidence_id`s it was given (claim records included), and any invented citation is stripped before persistence, so evidence-grounding audits stay valid. Off by default; requires `CS_ANTHROPIC_API_KEY`.
- **Cross-paper comparison** (`cs scout compare --paper <id> --paper <id> [--dim methods --dim results ...]`): side-by-side comparison of specific papers along named dimensions (defaults to problem/methods/results/limitations), served by the retrieval `POST /synthesis/compare` endpoint and rendered as a dimension × paper matrix. Useful when weighing candidate baselines during Approach/Experiment. Read-only — the comparison is not persisted; it complements (does not replace) Scout's grounded per-family synthesis.

### CS-EPIC-ONTOLOGY: PSZ Semantic Layer

Database-backed taxonomy for personal sound zone domain concepts, replacing hardcoded keyword dictionaries.

- **OntologyTerm** with 6 categories: method, metric, hardware, failure_mode, acoustic_goal, scene_assumption
- **OntologyRelationship** for term-to-term links (related_to, subsumes, alias_of)
- 63 seed terms across all categories, seeded via Alembic migration or the idempotent `cs ontology seed` command (also seeds `related_to` method relationships from `domain.RELATED_METHODS`)
- CRUD API + merge operation (merges keywords, moves relationships, updates evidence records, deprecates source)
- Scout automatically loads ontology terms from DB for classification
- **Corpus-derived, goal-scoped method taxonomy** (`cs ontology derive <goal_id>`): instead of forcing every goal into the fixed 7 seed method families, Claude induces the method families actually present in that goal's corpus from a broad retrieval sample, and persists them as goal-scoped `OntologyTerm`s (`workspace_id == goal_id`). Terms with `workspace_id = NULL` are the shared global seed. Scout's term loader is goal-aware: per category, goal-scoped terms override the global seed when present (methods use the derived set; metric/hardware/failure_mode stay global). A goal with no derived taxonomy falls back to the global seed. Use `--dry-run` to review induced families without persisting, and `cs ontology list -w <goal_id>` to inspect derived terms.
- **Pinned method families** (`cs goal pin <goal_id> <family>...` or `cs goal create --pin`): induction is a sample-plus-LLM step, so a given `derive` may or may not name a goal's defining technologies as standalone families. A goal can declare *must-have* families (stored as `pinned_method_families`, canonicalized to snake_case) that induction is instructed to include and that are guaranteed to be persisted — reserved against the `--max-families` budget and never truncated — even if the agent omits them. `cs ontology derive --pin <family>` adds ad-hoc pins on top of the goal's declared set for a single run.
- **Corpus-grounded induction** (`CS_TAXONOMY_GROUND_IN_CORPUS`, default on): to reduce the non-determinism of pure LLM induction, the derive step feeds the corpus's real Method entity nodes into the induction prompt. It fetches `GET /entities/papers/{id}` for the sampled papers (bounded to 15 papers / 40 method names) and lists those Title Case Method-node names as grounding hints, asking the agent to align a family's `canonical_name` to a node when they correspond — so the induced taxonomy reconciles with the GraphRAG graph rather than drifting on wording. Hints are advisory: only families actually supported by the chunks are kept, and pinned-family guarantees are unchanged. Whole-corpus embedding topic clusters (`GET /advanced/topics/clusters`) can be added as weak hints via `CS_TAXONOMY_USE_TOPIC_CLUSTERS` (default off — the endpoint recomputes k-means on demand and is slow; the call is bounded by `CS_TAXONOMY_CLUSTER_TIMEOUT` and failures degrade to no hint).

### CS-EPIC-APPROACH: Approach Card Generation and Curation

Synthesizes scout evidence into structured Approach Cards — one per method family — for comparing candidate research approaches.

- **ApproachCard** lifecycle: `generated` → `reviewed` → `scored` → `experiment_proposed` → `submitted` → `tested` → `validated` / `refuted` / `inconclusive` → `superseded`
- Synthesis-backed generation: when a scout-stage `EvidenceSynthesis` exists for a method family, the card's mechanism summary, metrics, open questions, hardware, and risks come from the Claude synthesis; falls back to algorithmic extraction from evidence groups otherwise
- Every field traced to source evidence records with direct/inferred evidence type
- Duplicate detection across approach cards within a workspace
- Merge operation combines evidence, metrics, hardware, risks; supersedes source card
- Maturity inference (theoretical, simulated, measured, validated) from evidence text

#### Execution evidence links (CS-APPROACH-008…011)

Approach Cards close the loop back from execution: `GET /goals/{id}/approaches/{approach_id}/execution-evidence` links a card to every downstream Experiment Card, ExecutionBatch, RunRequest, ResultBundle, and validation aggregation it produced.

- **Linked evidence** (CS-APPROACH-008): per-experiment blocks carry execution status, run-request IDs, result-bundle IDs, and the experiment's validation summary
- **Provenance groups** (CS-APPROACH-009): counts split literature/inference (`source_literature`, `inferred_synthesis`, `generated_hypotheses`) from execution (`approved_experiments`, `completed_validation`, `failed_validation`, `inconclusive_validation`)
- **Forward-only status refresh** (CS-APPROACH-010): after each ResultBundle ingest, a linked approach advances (never regresses) from validation aggregation — any passing sweep → `validated`, all-failing → `refuted`, otherwise → `inconclusive`; submitted-but-unvalidated cards sit at `submitted`/`experiment_proposed`
- **Negative evidence as signal** (CS-APPROACH-011): failed/inconclusive bundles surface failure type, summary, deviations, and retryability, plus deduplicated suggested follow-ups (retry vs. revise)

### CS-EPIC-CRITIC: Adversarial Approach Review

LLM critic that reviews `generated` approach cards before scoring, catching reasoning flaws the algorithmic scorer cannot see.

- **ApproachCritique** per card: Claude judges grounding fidelity (claims vs cited evidence), device fit, and maturity honesty, returning a structured verdict via forced Anthropic tool-use
- Verdicts: `advance` (sound, ready to score), `revise` (fixable issues), `refute` (unsound or device-mismatched)
- Grounding guard: any `cited_evidence_ids` the model invents are stripped before persistence (mirrors scout synthesis)
- **Recommend-only by default** — writes critiques and transitions nothing; opt-in `--apply` acts on verdicts (`advance`→`reviewed`, `refute`→`refuted`; `revise` never transitions)
- Each run logged via the governance agent-action audit trail

#### Closing the `revise` loop (`cs approach revise <goal_id>`)

The critic marks fixable cards `revise` but leaves them `generated`; `revise` reworks them with an LLM instead of a human. For each card whose latest critique verdict is `revise`, Claude receives the card, its critique (grounding / device-fit / maturity issues), and the card's cited evidence, then rewrites it via forced tool-use to: re-ground overclaims to the cited evidence, re-map `device_relevance`/`hardware_requirements` onto the goal's actual target device (rather than inheriting the source paper's rig), and correct maturity to match the evidence.

- **Supersede with provenance** — a revision creates a *new* card (`revised_from_id` → source) and marks the source `superseded`; the audit trail is preserved
- Same grounding guard: invented `cited_evidence_ids` are stripped before the revised card's evidence links are built
- **Citation-less revisions are skipped** — if a revision cites nothing valid (empty `cited_evidence_ids`, or all ids invalid) the resulting card would have no evidence links and the critic could never verify it; such a revision is skipped (reported with `skipped_reason`) and its source is left `generated` so a re-run retries it, rather than superseding a good card with an ungrounded one
- **Dry run by default** — proposes revisions without persisting; opt-in `--apply` writes the new cards and supersedes their sources
- `POST /goals/{id}/approaches/revise` (`{apply, method_families?}`); each agent call logged in the governance audit trail

### CS-EPIC-SCORE: Evidence-Linked Rubric Scoring

Transparent, evidence-linked scoring system for evaluating and comparing approach cards across 10 weighted dimensions.

- **RubricScore** with 10 dimensions: evidence_strength, reproducibility, acoustic_performance, robustness, realtime_feasibility, hardware_feasibility, calibration_burden, composability, measurement_clarity, device_relevance
- Formula: `final_score = Σ(weight_i × score_i) - risk_penalty`
- 5 weight profiles: default, fastest_prototype, scientific_novelty, robustness, product_feasibility
- Each dimension score includes rationale, confidence, evidence links, and low-confidence flag
- Algorithmic scoring from approach card fields and evidence metadata
- Auto-transitions approach from `reviewed` → `scored` on first score
- Per-dimension comparison rankings across all scored approaches
- Pareto frontier analysis: identifies non-dominated approaches

#### Execution-evidence score updates (CS-SCORE-008…012)

When a ResultBundle is ingested and an Experiment Card's validation aggregation is recomputed, the linked Approach Cards' `evidence_strength` score and confidence move to reflect real execution evidence — closing the loop from literature-only scoring to validated outcomes.

- **Execution evidence types** (CS-SCORE-008): `approved_experiment_design`, `queued_experiment`, `completed_experiment`, `failed_experiment`, `validation_passed`, `validation_failed`, `mixed_validation` — distinguishing validated results from literature/inference
- **ScoreUpdate** (CS-SCORE-009): every adjustment records previous/new score, score delta, previous/new confidence, confidence delta, validation status, evidence type, ResultBundle references, and a human-readable rationale
- **Idempotent** (CS-SCORE-010): keyed on the triggering ResultBundle ingestion key + approach + dimension, so a replayed ingestion applies no additional delta
- **Uncertainty-aware** (CS-SCORE-011): clean `passed`/`failed` outcomes move confidence fully (and score up/down); `mixed`/`partial` move confidence cautiously with no directional score change; `blocked` erodes confidence. Magnitudes are configurable via `CS_SCORE_EXECUTION_DELTA` / `CS_SCORE_CONFIDENCE_DELTA`
- **Batch explainability** (CS-SCORE-012): each update carries aggregate run count, passed/failed/missing counts, and aggregate metric summaries — including cross-run `variance`/`stddev` so a high-variance sweep is visibly less trustworthy than a tight one
- Queryable via `GET /goals/{id}/score-updates` (filter by `approach_id`, `experiment_id`)

### CS-EPIC-HYPOTHESIS: Hypothesis and Combination Generation

Generates HypothesisCards — proposed combinations of 2+ scored approaches — with compatibility analysis, rationale, and testability artifacts.

- **HypothesisCard** with 4-state lifecycle: `generated` → `reviewed` → `experiment_proposed` → `superseded`
- Two hypothesis types: `conservative` (both high-scoring, no conflicts) and `exploratory` (complementary strengths, may have flagged conflicts)
- Pairwise compatibility analysis: shared hardware (matched on canonical hardware concepts, not verbatim prose), conflicting assumptions, complementary rubric dimensions, ontology relationships
- Assumption conflict detection via negation patterns ("does not require", "no ", "without ")
- Complementary dimension detection using configurable thresholds (high ≥ 0.6, low ≤ 0.4)
- Deterministic generation from rubric scores, ontology relationships, and hardware overlap
- Deduplication against existing hypotheses by sorted approach ID sets
- Each hypothesis includes rationale, assumptions, expected benefits, failure modes, and required experiments

### CS-EPIC-APPROVAL: Human Approval and Execution Handoff

Immutable audit trail for experiment approval decisions, with gated status transitions and duplicate management.

- **ApprovalDecision** — immutable audit record (no `updated_at`): decision (approve/reject/request_edit), reviewer_id, reason, resource_flags, created_at
- Three decision types drive experiment status as a side effect: `approve` → `approved`, `reject` → `superseded`, `request_edit` → back to `generated` (bypasses public state machine)
- Automatic resource flag inference: `high_cost`, `gpu`, `treble` inferred from experiment card fields; reviewer can override
- On approve with no reason: YAML export stored automatically as handoff payload
- `list_pending()` surfaces all `reviewed` experiments, optionally filtered by goal
- `duplicate_experiment()` creates an editable copy (status=`generated`, name+" (copy)") with no decisions

**RunRequest submission** (approved card → RunRequests, `POST /experiments/{id}/submit`): the co-scientist hands an approved card to the external Experimentation System as one or more RunRequests instead of executing it directly.

- **Sweep expansion**: uses the RunRequest preview to expand the card into per-run parameter sets, creating one `RunRequestReference` per run under a single `ExecutionBatchReference` (CS-EXEC-001/002). The external RunRequest API call is abstracted behind `submission.run_request_submitter` so a live client can be swapped in.
- **Full correlation on every RunRequest** (CS-EXEC-007): each `RunRequestReference` carries the `correlation_id`, `goal_id`, `experiment_id`, `execution_batch_id`, plus the `hypothesis_id` and `approach_ids` it tests — so events from the Experimentation System reconcile directly to Approach/Hypothesis cards without traversing the Experiment card.
- **Approval policy on every batch** (CS-APPROVAL-008): `approval_id`, `approver`, `approved_at`, `cost_class` (defaults to the card's estimated cost), `credentialed` flag, `resource_policy` (required capabilities + overrides), and `retry_policy` are stored on the `ExecutionBatchReference`.
- **Batch approval modes** (CS-APPROVAL-009): `approve_batch` submits all runs as `pending`; `approve_each_run` submits every run as `blocked` awaiting per-run approval; `approval_required_above_threshold` blocks runs only when the expanded count exceeds `approval_threshold`. The resulting card `execution_status` follows the batch rollup (`submitted` vs `blocked`).
- **Idempotent**: a fully-submitted card (carries an `execution_batch_id` with `handoff_status == "submitted"`) is rejected (409); re-registering the same RunRequest returns the existing reference. Submission requires `approved` status.
- **Failed handoff + idempotent retry** (CS-APPROVAL-010): if the external RunRequest call raises, the batch and any RunRequests already handed off are preserved, the card is marked `handoff_status = "failed"`, and a `HandoffRequest` records the error, timestamp, payload summary, approval id, and retryability (the endpoint returns 502). `POST /experiments/{id}/retry` re-runs the handoff into the *same* batch — each preview run is matched against existing `RunRequestReference` parameters so runs already accepted are reused, never duplicated.
- **Cancel / resubmit requests** (CS-APPROVAL-011): `POST /experiments/{id}/cancel` and `.../resubmit` relay a control request to the Experimentation System (abstracted behind `handoff.cancellation_requester` / `resubmission_requester`) and record a `HandoffRequest` with the returned status. Execution control stays with that system — cancelling only records the request; run statuses change only when the system reports them back. `GET /experiments/{id}/handoff-requests` lists the recorded requests.

### CS-EPIC-VALIDATION: Agent-Driven Experiment Validation

Closes the experiment feedback loop by ingesting measured results, evaluating them against pass conditions via a Claude Sonnet 4.6 agent, and driving automated status transitions on experiments and approach cards.

- **ValidationResult** — immutable audit record (no `updated_at`): decision (validated/refuted), confidence, reasoning, per-criterion results, refinement suggestions, measured metrics, artifact paths, model used
- `POST /{eid}/results` accepts measured metrics (and optional artifact paths) from any source: Experiment Runner, MLflow script, or manual submission
- Claude Sonnet 4.6 agent receives full context — experiment spec, pass conditions, measured values, approach card, goal success criteria — and returns structured JSON with per-criterion pass/fail evaluation
- Automated side effects on validation: experiment `running → completed` (validated) or `running → failed` (refuted)
- Automated side effects on approach: `experiment_proposed → tested → validated` or `tested → refuted`; maturity advanced to `simulated` (simulation) or `measured` (measurement/hybrid); maturity never downgraded
- **Reproduction status taxonomy** (CS-VALIDATION-005): each result carries a `reproduction_status` derived from per-criterion outcomes — `reproduced` (all passed), `partially_reproduced` (some passed), `failed` (none passed), `blocked` (nothing measurable), `superseded` (a later re-run replaced this result)
- **Roadmap feedback loop** (CS-VALIDATION-006): ingesting a result auto-retires open roadmap items linked to the experiment via `source_experiment_id`, so the next-best recommendations reflect what was just learned
- Single `db.commit()` at end of orchestration — no nested commits across status transitions
- Refinement suggestions populated when refuted to guide next iteration

**ResultBundle ingestion + aggregation** (Experimentation System results, `POST /result-bundles`): the automated counterpart to the agent path — structured ResultBundle summaries from the external runner are ingested and rolled up per Experiment Card.

- **ResultBundleReference** (CS-VALIDATION-007/009): links result bundle ID, RunRequest/run/attempt IDs, Experiment Card, Hypothesis Card, Approach Cards, and ExecutionBatch, plus metrics, validation status, artifacts, deviations, warnings, and provenance. Missing links default from the Experiment Card.
- **Idempotent ingestion** (CS-VALIDATION-008): keyed on `(run_request_id, run_id, attempt_id)`. Replayed completion events return `duplicate: true` and never double-count runs or metric summaries.
- **Failure diagnostics** (CS-VALIDATION-010): failed bundles carry `failure_type`, `failure_summary`, `retryable`, partial `artifacts`, and `deviations` so failures still inform decisions.
- **ValidationAggregation** (CS-VALIDATION-011, `GET /experiments/{id}/validation-aggregation`): one row per experiment collapsing bundles to the latest attempt per run, computing an aggregate status — `passed`, `failed`, `mixed`, `blocked`, `inconclusive`, or `partial` (when expected runs are still missing) — with per-metric summaries (count/min/max/mean/variance/stddev, CS-SCORE-012) and a `missing_runs` count.
- **Partial-aggregation score gate** (CS-VALIDATION-012): a bundle flagged `is_partial` or a batch still missing runs marks the aggregation partial and, by default, does **not** drive an approach score update — evidence stays provisional until the batch completes. Set `CS_SCORE_UPDATE_ON_PARTIAL=true` to update scores from partial evidence.
- **Artifact manifest + access labels** (CS-VALIDATION-013): each bundle stores a `manifest_uri`, `artifact_visibility` (default `internal`), and a permission-aware `access_label` alongside the `artifacts` map, surfaced in the validation view so researchers can inspect plots/logs/metrics with the right access context.
- **Execution sync**: ingesting a bundle advances the linked `RunRequestReference` (passed→completed, failed→failed, blocked→blocked), which rolls up through the batch to the card's `execution_status`.

### CS-EPIC-DEVICE: Candidate Device Concept Synthesis

Closes the research-to-device loop by synthesising validated approach cards — with their rubric scores, experiments, and validation results — into actionable candidate device architectures via a Claude Sonnet 4.6 agent.

- **DeviceConceptCard** with 3-state lifecycle: `generated` → `reviewed` → `superseded`
- Claude Sonnet 4.6 Device Integrator Agent receives full context — goal constraints, validated approaches with rubric scores, hardware requirements, experiments, and validation outcomes — and proposes one device concept per viable form factor (desktop_bar, headrest, monitor_speaker_array, etc.)
- Each card stores form factor, use case, acoustic architecture (control stack, calibration, simulation backing), hardware spec (speakers, microphones, compute), and expected performance as structured JSON
- Full traceability: `approach_ids`, `experiment_ids`, `validation_result_ids` link back to all source artefacts
- `unresolved_risks` and `next_steps` fields turn each concept into an actionable research roadmap
- Side-by-side comparison across ≥2 concepts: form factor, maturity, confidence, approach count, validation passed/failed counts, risk count, next step count
- Export as markdown (human-readable handoff with all sections) or JSON
- Maturity inherited from weakest contributing approach

#### Device updates from execution evidence (CS-DEVICE-007…010)

Device Concept Cards close the loop back from execution: as ResultBundles are ingested, a concept's architecture confidence and unresolved risks update from the validation outcomes of the experiments testing its approaches.

- **Linked evidence** (CS-DEVICE-007): `GET /goals/{id}/devices/{device_id}/execution-evidence` reports per-experiment validation status, passing metrics, failed assumptions, result-bundle IDs, execution batch, and the current `evidence_strength` score of each supporting approach
- **Risks from failure** (CS-DEVICE-008): failed/inconclusive validation adds canonical unresolved risks — latency, robustness, calibration burden, hardware feasibility, low-frequency leakage — mapped from ResultBundle failure types (deduped, additive)
- **Confidence from evidence** (CS-DEVICE-009): confidence is recomputed deterministically from linked experiment aggregations (base 0.5, passing raises, failing/inconclusive lowers); each change records a **DeviceEvidenceUpdate** with supporting ResultBundles, affected approach scores, added risks, and rationale — idempotent on the triggering ingestion key. Queryable via `GET /goals/{id}/devices/evidence-updates`
- **Comparison by tested performance** (CS-DEVICE-010): the side-by-side view includes confidence and validation passed/failed counts

### CS-EPIC-ROADMAP: Research Roadmap and Next-Best Experiment Planning

Synthesises the full state of a research goal — approaches, experiments, validation outcomes, device concepts, and rubric scores — into a ranked, lane-sorted roadmap of recommended next actions via a Claude Sonnet 4.6 Research Program Manager Agent.

- **ResearchRoadmapItem** with 3-state lifecycle: `open` → `completed` | `superseded`
- Three research lanes: `conservative` (low-risk near-term validation), `exploratory` (higher-risk higher-upside novel combinations), `device_prototype` (hardware and integration steps)
- Agent assigns `priority_score` (0–1) by weighing estimated information gain, device relevance, and cost; items returned ranked highest-first within a generation run
- Agent explicitly identifies evidence gaps per approach and surfaces "run scout for X method family" items
- **Structured evidence gaps** (CS-ROADMAP-003): `GET /roadmap/evidence-gaps` (and `cs roadmap gaps`) returns, per promising approach, the claim fields lacking evidence links and the weak/low-confidence rubric dimensions — the "what must be tested" view that is also fed into the roadmap agent's context
- Auto-retire: when an experiment transitions to `completed` or `failed`, all `open` roadmap items linked via `source_experiment_id` are automatically retired to `completed` — no manual cleanup needed
- Idempotent generation: each `POST /generate` creates a fresh `generation_run_id` batch; prior items remain in DB with their original status for audit
- Full traceability: each item links back to `source_approach_ids`, `source_experiment_id`, and/or `source_device_id`

**Roadmap updates from execution outcomes** — as ResultBundles are ingested and an Experiment Card's validation aggregation is recomputed, the roadmap reacts automatically (no re-generation needed). The whole refresh is a deterministic projection of the current aggregation, so replayed ingestions never double-create follow-ups or drift ranks.

- **Outcome on linked items** (CS-ROADMAP-006): items that planned the experiment (linked via `source_experiment_id`) pick up its `execution_outcome` — `passed`/`failed` complete the item, `inconclusive` (blocked/mixed) leaves it open for more evidence
- **Failure follow-ups** (CS-ROADMAP-007): a failed experiment auto-spawns actionable follow-up items — *rerun with changed assumptions*, *add a baseline*, *inspect failure artifacts*, *adjust target metric or tolerance*, *test a simpler scenario* — inheriting the experiment's approaches and deduped by title so re-ingestion adds none
- **Validation-aware ranking** (CS-ROADMAP-008): every item gets an `evidence_adjusted_score` folding in outcome, information gain, cost, lane risk, device relevance, and open evidence gaps; `GET /roadmap` orders by this score (falling back to the agent's `priority_score`) and `priority_rank` is recomputed goal-wide
- **Provisional partial-batch updates** (CS-ROADMAP-009): a still-incomplete (partial) batch marks linked items `provisional` and spawns provisional follow-ups on early failure; once the batch finishes they are confirmed (final failure) or superseded (final pass)

### CS-EPIC-EXPERIMENT: Experiment Card and Spec Generation

Generates ExperimentCards — structured experiment proposals from approach cards and/or hypothesis cards — with objectives, baselines, parameter sweeps, validation criteria, and exportable specs.

- **ExperimentCard** with 7-state lifecycle: `generated` → `reviewed` → `approved` → `running` → `completed` / `failed` → `superseded`
- Dual source linking: `approach_ids` for direct approach experiments + optional `hypothesis_id` for hypothesis-driven experiments
- Algorithmic generation: single-approach validation experiments + comparative pairwise experiments
- PSZ-specific parameter sweeps: speaker count, listener shift, reverberation condition, frequency bands, calibration error
- Baseline selection from `domain.RELATED_METHODS` + universal `delay_and_sum_beamforming` baseline
- Validation criteria derived from goal success criteria (operator-aware: `>=` → `_min`, `<=` → `_max`)
- Cost/runtime estimation from parameter sweep cardinality (configurable thresholds)
- 10-dimension experiment rubric scoring: hypothesis clarity, device relevance, baseline quality, metric quality, reproducibility, information gain, cost/time, failure informativeness, robustness coverage, artifact quality
- YAML and Python config export without external dependencies
- Deduplication against existing experiments by approach ID sets

**Execution handoff schema** (Experimentation System integration — the co-scientist hands approved cards off as RunRequests, it does not execute them):

- **Separated lifecycles**: the card's approval `status` (now `generated`, `needs_review`, `reviewed`, `approved`, `rejected`, `duplicated`, `superseded`, `archived`; legacy `running`/`completed`/`failed` retained) is distinct from `execution_status` (`not_submitted` → `submitted` → `queued` → `running` → `partially_completed` → `completed` / `failed` / `blocked` / `mixed_outcome`), each with its own guarded transition table. "Approved" no longer implies "executed."
- **Handoff fields** on every card: `execution_handoff` block (`submission_mode`, `handoff_status`, `experiment_control_plane`, `required_capabilities`, `runner_pool_preference`, `run_request_ids`, `execution_batch_id`, `result_bundle_ids`, `batch_expansion`, `expected_run_count`)
- **Submission modes**: `single_run`, `run_request_batch`, `sweep_batch`. Synthesised sweep cards default to `sweep_batch` with `expected_run_count` from the sweep cardinality; required capabilities are derived from runtime + experiment type
- **RunRequest preview** (`GET /experiments/{id}/run-request-preview`, `cap` param): Cartesian-expands the sweep into per-run parameter dicts (capped, `truncated` flagged), reporting expanded run count, variables, required capabilities, cost/runtime, and the approval implication — so a researcher sees how many runs a sweep creates before submitting
- **Execution status endpoint** (`POST /experiments/{id}/execution-status`, `force` for idempotent syncs) advances the execution lifecycle independently of approval

### CS-EPIC-EXECUTION: Execution Batch and Run Tracking

The co-scientist does not execute experiments — it hands approved cards to the external Experimentation System and keeps *references* to the objects that system owns. Status updates arrive by poll or webhook and roll up into an aggregate batch status and each Experiment Card's `execution_status`.

- **Reference model, not execution**: three co-scientist-side tables — `ExecutionBatchReference`, `RunRequestReference` (unique on the external `run_request_id`), and `RunAttemptReference` (surfaces retries/failures) — track state without owning runner internals. Correlation IDs (`corr-…`) tie references back to control-plane objects.
- **RunRequest status** (`pending`, `queued`, `running`, `completed`, `failed`, `canceled`, `blocked`, `timed_out`) is ingested idempotently; re-registering the same `run_request_id` returns the existing reference.
- **Aggregate batch rollup**: `recompute_batch` recounts member runs into per-status counts and derives a `BatchAggregateStatus` (`submitted`, `queued`, `running`, `partially_completed`, `completed`, `failed`, `mixed_outcome`, `blocked`, `canceled`) — terminal-but-mixed batches resolve to `mixed_outcome`; any completed/failed alongside non-terminal runs resolves to `partially_completed`.
- **Card sync**: every rollup best-effort syncs the owning Experiment Card's `execution_status` (via `set_execution_status(..., force=True)`); a missing/archived card never breaks ingestion.
- **Endpoints**: `POST /execution-batches`, `GET /goals/{id}/execution-batches`, `GET /execution-batches/{id}`, `POST /run-requests` (register), `GET /run-requests` (filter by `batch_id`/`experiment_id`), `GET /run-requests/{id}`, `POST /run-requests/{id}/status` (ingest update), `POST|GET /run-requests/{id}/attempts`.

### CS-EPIC-GOVERNANCE: Agent Orchestration and Governance

Adds an immutable audit trail over every agent-driven Claude call and a corpus/experiment permission model that can disable agent actions per goal.

- **AgentActionLog** — append-only audit record (no `updated_at`, no delete endpoint): service, action, model used, prompt/completion token counts, elapsed ms, response summary (first 512 chars), and error string when the call raised
- Every instrumented agent (validation, device, roadmap) records one log row per Claude call via `log_agent_call()`, which `flush`es into the caller's existing transaction — the row is persisted atomically with the primary artefact at no extra commit
- `log_agent_call()` never raises: logging failures are swallowed and printed to stderr so audit instrumentation can never break the primary workflow
- Queryable via `GET /goals/{id}/agent-logs` (filter by service) and `GET /goals/{id}/agent-logs/{log_id}`, or the `cs logs` CLI
- **Permission model**: `is_restricted` flag on `ResearchGoal` (toggled via `PATCH /goals/{id}`). When set, `raise_if_restricted()` at the top of each generate service returns 403 — blocking validation, device, and roadmap agent actions while leaving read endpoints intact

#### Execution boundary and handoff accountability (CS-GOV-007…010)

The co-scientist is a planning, approval, and interpretation layer — **not** the experiment execution system. Compute, credentials, containers, and solvers are governed by the external Experimentation System. Experiments run only via RunRequest handoff; the co-scientist records references, never results it produced itself.

- **Simulation Handoff Agent** (CS-GOV-007): the execution-touching agent is scoped to *submit RunRequests, monitor status, and ingest results*. It does not start containers, run commands, allocate GPUs, or operate solvers. Name exposed as `governance.HANDOFF_AGENT_NAME` and used as the default audit actor
- **Execution boundary** (CS-GOV-008): `assert_execution_boundary()` guards the direct repro-runner path. When `CS_ENFORCE_EXECUTION_BOUNDARY=true`, direct execution returns 403 and the only sanctioned route is RunRequest submission. Defaults to `false` so the legacy synchronous runner remains available in dev
- **ExecutionAuditLog** (CS-GOV-009): append-only accountability trail for every execution-related action — `handoff_submitted`, `run_status_updated`, and `result_bundle_ingested`. Each row records the submitter/actor, approval ID, Experiment Card ID, execution batch ID, RunRequest IDs, governing policy, a stable SHA-256 payload checksum, and an action detail blob. Written via `record_execution_event()`, which `flush`es into the caller's transaction and never raises
- Queryable via `GET /goals/{id}/execution-audit` (filter by `action` and `experiment_id`)
- **Permission-checked references** (CS-GOV-010): execution references stay scoped to their goal workspace; restricted goals disable agent actions across the execution surface
- **Redaction of runner internals** (CS-GOV-011): `governance.redact_runner_internals()` strips secrets, credential names, local filesystem paths, raw runner logs, and operator-only diagnostics from data bound for the UI/API. Secrets are always redacted; runner internals and local paths are redacted unless the caller is an authorized (operator) viewer. Applied to `ResultBundle` artifacts and provenance whose `artifact_visibility` is `restricted`/`operator_only`
- **Evidence labels** (CS-GOV-012): `derive_evidence_label()` labels an experiment's evidence state — `proposed`, `approved`, `queued`, `completed`, `failed`, `validation-passed`, `validation-failed`, `mixed`, or `inconclusive` — so a speculative plan is never displayed as a validated result. Precedence is validation outcome > execution lifecycle > approval lifecycle. Surfaced as a badge on the experiment detail page and via `GET /goals/{id}/experiments/{experiment_id}/evidence-label`

### CS-EPIC-UI: Web User Interface

A server-rendered web UI for reviewing, editing, scoring, and curating already-generated artefacts — the first graphical alternative to the `cs` CLI and raw REST calls.

- **Stack**: Jinja2 templates + [HTMX](https://htmx.org) (loaded from CDN), mounted on the existing FastAPI app under `/ui`. No Node toolchain, no build step, one hand-written CSS file
- **Thin adapter**: every route calls the existing service functions via `Depends(get_db)` and renders their Pydantic responses — no new business logic, DB models, or migrations
- **Workspace dashboard** (`/ui/goals/{id}`): goal summary plus counts and links for evidence, approaches, experiments, validation, devices, and roadmap
- **Approach review**: inspect, edit, approve, reject, merge, and score approach cards; approve/reject/score actions return HTML partials that HTMX swaps in place
- **Hypothesis review**: list hypothesis combinations with type/conflict badges, inspect rationale, component approaches, and per-pair compatibility (shared hardware, ontology relation, conflicts), and mark generated hypotheses as reviewed
- **Score explanation panel**: per-dimension score, weight, rationale, and evidence citations (algorithmic scoring — no Claude call)
- **Experiment editor**: review and modify generated experiment specs, with YAML/Python export
- **Read-only views** for validation results, device concept cards, and the research roadmap
- All UI flows are deterministic (zero Claude calls); generation triggers remain in the CLI/API

#### Execution status UI (CS-UI-008…013)

Surfaces the execution-tracking state added by the experimentation-integration epics. The co-scientist only *records references* to work the external Experimentation System runs — the UI reflects that boundary and never triggers a run.

- **Separate lifecycle and execution badges** (CS-UI-008): the experiment detail header shows the card's lifecycle `status` and its `execution_status` as distinct badges, so a `reviewed` card that is `running` reads unambiguously
- **ExecutionBatch panel** (CS-UI-009): per experiment, each submitted batch shows its aggregate status, submission mode, and a RunRequest count table (total / queued / running / completed / failed / canceled / blocked / timed out), plus a per-run-request list with status and timestamps
- **ResultBundle summaries in the validation view** (CS-UI-010): the validation page gains an "Execution results" section listing each experiment's ingested ResultBundles (bundle id, run request, validation status, artifact manifest link + visibility/access labels, failure summary) alongside its validation aggregation
- **Aggregation policy + score-update status** (CS-UI-011): incomplete batches and partial bundles are flagged with a `partial` badge, the aggregation line spells out passed / failed / blocked / missing counts against the expected run count, and a badge states whether approach score updates were **applied** or **held** under the partial-aggregation policy (CS-VALIDATION-012); a per-metric table shows count/mean/stddev/min/max
- **Negative execution evidence on approaches** (CS-APPROACH-011): the approach detail page renders an "Execution Evidence" section — evidence-group counts, per-experiment negative-evidence tables (bundle, status, failure, deviations, retryability), and deduplicated suggested follow-ups
- **Score provenance + affected roadmap** (CS-UI-013): the experiment detail page shows the execution-driven score updates for its approaches — before/after score and confidence, the rationale, and the linked ResultBundle references — plus the roadmap items that trace back to the experiment's outcomes
- **Handoff control requests, read-only** (CS-UI-012): the experiment detail page lists recorded handoff-control requests — failed handoffs, retries, and cancel/resubmit relays — with type, status, retryability, and detail. This is a read-only projection of state recorded by the cancel/resubmit/retry API; the UI does not drive execution control itself (that stays with the Experimentation System)
- Everything is read-only projection of stored references; the UI never submits, cancels, or resubmits runs

### CS-EPIC-EVALUATION: Observability, Evaluation & Quality Metrics

A read-only metrics layer that computes the quality targets from PRD §20 over the artefacts already in the workspace. No new DB models, migrations, or Claude calls — every metric is derived deterministically from existing state.

- **Approach Card usefulness** (CS-EVAL-001): usefulness rate from the approach lifecycle (reviewed/scored/.../validated vs superseded/refuted; target ≥ 75%) plus evidence traceability (cards with ≥ 1 evidence link; target 100%)
- **Evidence grounding** (CS-EVAL-002): per claim-bearing field, classify as grounded (a `direct` evidence link), inferred (only `inferred` links), or unsupported (content but no link). Reports grounding rate (target ≥ 90%), unsupported claim rate (target ≤ 5%), and the list of unsupported claims for diagnosis
- **Experiment quality** (CS-EVAL-003): acceptance rate from experiment status (reviewed/approved/running/completed vs superseded; target ≥ 70%) and spec validity (specs that pass schema validation; target ≥ 85%)
- Each metric reports raw counts, the rate, the PRD target, and a pass/fail gate. Empty workspaces are not failing gates
- **Productivity metrics** (CS-EVAL-005): estimated time saved is a heuristic over the governance agent-action log (successful Claude calls × `CS_EVAL_MINUTES_PER_AGENT_ACTION`), reported alongside the user-satisfaction rate computed from captured feedback
- **User feedback capture** (CS-EVAL-006): a lightweight feedback store records thumbs up/down plus an optional comment against any artefact (approach, score, experiment, device, hypothesis, roadmap); satisfaction rate feeds the productivity block
- **Execution-handoff metrics** (CS-EVAL-007…009), all derived from stored handoff state — the co-scientist only records the handoff, it never runs anything:
  - **Handoff success** (CS-EVAL-007): from the Experiment Card handoff lifecycle, the share of attempted handoffs that reached `submitted` (target ≥ 95%), plus successful RunRequest count and retry-success rate (run requests that took ≥ 2 attempts and completed)
  - **Execution traceability** (CS-EVAL-008): every RunRequest should trace back to research intent — goal, Experiment Card, Approach Card, hypothesis (where applicable), and a `handoff_submitted` approval record; reports the fully-traceable rate (target 100%) and the ids of any untraceable run requests
  - **Idempotent ingestion** (CS-EVAL-009): verifies zero duplicate ResultBundles (by ingestion key) and zero duplicate score updates (by source_key/approach_id/dimension) — a nonzero count means the idempotency guarantee was violated
  - **Status freshness** (CS-EVAL-010): flags in-flight RunRequests whose mirrored status has not updated within `CS_EVAL_STATUS_FRESHNESS_THRESHOLD_SECONDS`, so stale execution-status displays (polling lag) are detectable
  - **Failed-run usefulness** (CS-EVAL-011): share of failed ResultBundles that remain useful evidence — carrying a failure reason, diagnostic artifacts, and a linked roadmap follow-up (target ≥ 90%)
  - **Batch aggregation quality** (CS-EVAL-012): diagnostic batch-completion, partial-aggregation, and mixed-outcome rates so sweep handling can be tuned
- Exposed via `GET /co-scientist/goals/{id}/evaluation[/...]`, the `cs eval` CLI group, and the `/ui/goals/{id}/evaluation` page

## Setup

```bash
# Prerequisites: Python 3.12, uv
uv venv && uv pip install -e ".[dev]"
source .venv/bin/activate

# Initialise the database
alembic upgrade head

# Start the API server (terminal 1)
uvicorn coscientist.main:app --reload --port 8001
```

The CLI (`cs`) talks directly to the database — the API server is only needed if you want to hit the REST endpoints directly.

## Web UI

```bash
uvicorn coscientist.main:app --reload --port 8001
```

Then visit `http://localhost:8001/ui` (redirects to the goal picker). Pick a goal to open its dashboard, then drill into Approaches to review, edit, approve/reject, merge, and score cards in place, into Hypotheses to inspect combinations and mark them reviewed, or into Experiments to edit specs and export YAML/Python. Validation, Devices, and Roadmap are read-only views. The UI reviews already-generated artefacts; use the CLI to run the generation steps below first.

## End-to-End Workflow

A complete run from goal to approved experiment. IDs are shown as `<X_ID>` — copy them from the table output of each `list` command (full UUIDs are printed).

### 1. Create and activate a research goal

```bash
cs goal create --name "PSZ Headphone" --app personal_sound_zones
cs goal list                        # copy GOAL_ID
cs goal activate <GOAL_ID>
```

### 2. Scout literature (requires retrieval API on port 8000)

```bash
cs scout run <GOAL_ID>
cs scout run <GOAL_ID> --synthesize             # also run Claude synthesis per method family
cs scout summary <GOAL_ID>          # check evidence counts and sparsity warnings
cs scout evidence <GOAL_ID> --group-by method   # review method families found
cs scout synthesis <GOAL_ID>                    # read the per-family Claude syntheses
```

### 3. Generate and review approach cards

Approach cards are generated one per method family found in the evidence.

```bash
cs approach generate <GOAL_ID>
cs approach list <GOAL_ID>          # copy APPROACH_IDs
cs approach show <APPROACH_ID>      # inspect evidence links, metrics, risks
cs approach review <APPROACH_ID>    # repeat for each approach worth keeping
```

If two approaches cover the same method, merge them:

```bash
cs approach merge --source <SOURCE_ID> --target <TARGET_ID>
```

Optionally run the LLM critic over the generated cards before scoring. It recommends
verdicts (advance / revise / refute) without changing anything; re-run with `--apply`
to act on them (`advance`→`reviewed`, `refute`→`refuted`):

```bash
cs critic run <GOAL_ID>             # recommend-only: verdicts + critiques, no transitions
cs critic show <GOAL_ID>            # read full critiques (issues, strengths)
cs critic run <GOAL_ID> --apply     # apply verdicts (prompts for confirmation; -y to skip)
```

Cards the critic marks `revise` stay `generated` — rework them with the LLM instead of
by hand. The revise agent rewrites each such card to address its critique (grounding,
device fit, maturity), creating a new card (`revised_from_id` → source) and superseding
the source. Dry-run by default; `--apply` persists:

```bash
cs approach revise <GOAL_ID>             # dry run: propose revisions, persist nothing
cs approach revise <GOAL_ID> --apply     # supersede sources with revised cards (-y to skip prompt)
cs critic run <GOAL_ID>                  # re-critique the revised cards, aiming for advance
```

### 4. Score and compare approaches

Hypothesis generation requires **at least 2 scored approaches**.

```bash
cs score run <GOAL_ID>              # scores all reviewed approaches
cs score compare <GOAL_ID>          # ranked table across all dimensions
cs score pareto <GOAL_ID>           # non-dominated (Pareto-optimal) set
cs score show <APPROACH_ID>         # per-dimension breakdown with rationale
```

To re-score with a different priority profile:

```bash
cs score run <GOAL_ID> --profile robustness
# profiles: default, fastest_prototype, scientific_novelty, robustness, product_feasibility
```

### 5. Generate and review hypotheses

Hypotheses combine 2+ scored approaches into testable propositions.

```bash
cs hypothesis generate <GOAL_ID>
cs hypothesis list <GOAL_ID>                    # copy HYPOTHESIS_IDs
cs hypothesis list <GOAL_ID> --type exploratory # filter by type
cs hypothesis show <HYPOTHESIS_ID>              # rationale, conflicts, required experiments
cs hypothesis review <HYPOTHESIS_ID>
```

### 6. Generate and score experiments

Experiments can be generated from the full scored approach set, a single approach, or a specific hypothesis.

```bash
cs experiment generate <GOAL_ID>                        # all scored approaches
cs experiment generate <GOAL_ID> --approach <ID>        # single approach
cs experiment generate <GOAL_ID> --hypothesis <ID>      # from hypothesis

cs experiment list <GOAL_ID>                            # copy EXPERIMENT_IDs
cs experiment show <EXPERIMENT_ID>                      # full spec with sweep params
cs experiment score <EXPERIMENT_ID> <GOAL_ID>           # 10-dimension quality score
cs experiment export <EXPERIMENT_ID>                    # YAML handoff spec
cs experiment export <EXPERIMENT_ID> --format python    # Python config dict
```

### 7. Approve experiments

Experiments must be transitioned to `reviewed` before the approval flow.

```bash
cs experiment review <EXPERIMENT_ID>

cs approval pending --goal <GOAL_ID>            # confirm it appears in the queue
cs approval approve <EXPERIMENT_ID> <GOAL_ID>   # → approved, YAML spec stored automatically
cs approval approve <EXPERIMENT_ID> <GOAL_ID> --reviewer "ryard" --reason "ready to run"

# If changes are needed instead:
cs approval request-edit <EXPERIMENT_ID> <GOAL_ID> --reason "add measurement baseline"
# experiment returns to 'generated'; edit and re-review

# Or reject outright:
cs approval reject <EXPERIMENT_ID> <GOAL_ID> --reason "superseded by hypothesis experiment"

# Audit trail and copy management:
cs approval history <EXPERIMENT_ID> <GOAL_ID>   # chronological decision log
cs approval duplicate <EXPERIMENT_ID> <GOAL_ID> # editable copy at 'generated' status
```

### 8. Run on the real simulator (automated)

An approved experiment can be executed against the [repro](../experiment) runner, which drives
real PSZ acoustic simulators. This replaces hand-typing metrics: co-scientist submits a spec to
repro, polls the run to completion, pulls `metrics.json`, translates the simulator's native
metric keys to co-scientist canonical names, transitions the experiment to `running`, and feeds
the measured values straight into the validation agent.

```bash
# Prerequisite: the repro API must be serving (default http://localhost:8003)
#   in the repro project:  repro serve

cs experiment run <EXPERIMENT_ID> <GOAL_ID>             # run → validate in one step
cs experiment run <EXPERIMENT_ID> <GOAL_ID> --timeout 900 --json
```

The simulator is chosen by the primary approach's method family:

| method family | repro simulator | native → canonical metrics |
|---|---|---|
| acoustic_contrast_control, beamforming, pressure_matching, null_steering | `vast_simulate.py` | `oAC_best_dB`→`acoustic_contrast_db`; `nsde_achieved_dB`→`bright_zone_error` |

Configure the endpoint via `CS_REPRO_URL` / `CS_REPRO_API_KEY` (see `config.py`). If no
simulator is registered for the method family — or the run produces no translatable metrics —
the command fails with a clear message and leaves the experiment `approved`; it never fabricates
results. Fall back to the manual path (step 9) in that case.

### 9. Submit results manually and validate

Once an experiment is `running`, submit measured metrics to trigger automated validation. (When
using the automated runner in step 8 this happens for you.)

```bash
cs validation submit <EXPERIMENT_ID> <GOAL_ID> \
  --metrics '{"acoustic_contrast": 18.5, "latency": 8.2}'

# Optional: attach artifact paths and notes
cs validation submit <EXPERIMENT_ID> <GOAL_ID> \
  --metrics '{"acoustic_contrast": 18.5}' \
  --artifacts '{"mlflow_run": "runs:/abc123"}' \
  --notes "Measured at 1kHz with 2 speakers"

cs validation show <EXPERIMENT_ID> <GOAL_ID>   # full result with per-criterion breakdown
cs validation list <GOAL_ID>                   # all results for the goal

# After validation the approach automatically transitions:
cs approach list <GOAL_ID> --status validated  # if all criteria passed
cs approach list <GOAL_ID> --status refuted    # if any criterion failed
```

### 10. Synthesise device concepts

With validated approaches in hand, generate candidate device architectures.

```bash
cs device generate <GOAL_ID>                        # agent proposes one concept per form factor
cs device list <GOAL_ID>                            # copy DEVICE_IDs
cs device show <DEVICE_ID> <GOAL_ID>                # full structured card

# Compare two or more concepts side by side:
cs device compare <DEVICE_ID_1> <DEVICE_ID_2> --goal <GOAL_ID>

# Export for stakeholder handoff:
cs device export <DEVICE_ID> <GOAL_ID>              # markdown (default)
cs device export <DEVICE_ID> <GOAL_ID> --format json

cs device review <DEVICE_ID> <GOAL_ID>              # mark as reviewed
```

### 11. Generate and manage the research roadmap

With approaches, experiments, and device concepts in place, generate a ranked view of what to do next.

```bash
cs roadmap generate <GOAL_ID>                        # agent produces 3–15 prioritised items
cs roadmap list <GOAL_ID>                            # all items, sorted by priority score
cs roadmap list <GOAL_ID> --lane conservative        # filter by lane
cs roadmap list <GOAL_ID> --status open              # only open items

cs roadmap show <ITEM_ID> <GOAL_ID>                  # full details with rationale and sources
cs roadmap complete <ITEM_ID> <GOAL_ID>              # manually mark an item as completed
```

After completing or failing an experiment, linked roadmap items retire automatically — no manual step needed.

### 12. Inspect agent logs and restrict a goal

Every agent-driven Claude call (validation, device, roadmap) is logged for audit.

```bash
cs logs list <GOAL_ID>                          # all agent calls, newest first
cs logs list <GOAL_ID> --service roadmap         # filter by service
cs logs show <LOG_ID> <GOAL_ID>                  # full record as JSON

# Restrict a goal to disable all agent actions (generate endpoints return 403):
curl -X PATCH localhost:8001/co-scientist/goals/<GOAL_ID> \
  -H "Content-Type: application/json" -d '{"is_restricted": true}'
```

## Command Reference

### Goals
```bash
cs goal create --name <NAME> --app <APP> [--pin FAMILY ...]
cs goal list [--status draft|active|archived]
cs goal show <GOAL_ID>
cs goal pin <GOAL_ID> <FAMILY> [<FAMILY> ...]   # set must-have method families for taxonomy induction
cs goal activate <GOAL_ID>
cs goal archive <GOAL_ID>
cs goal delete <GOAL_ID>
```

### Scout
```bash
cs scout run <GOAL_ID> [--method METHOD] [--top-k N] [--synthesize]
cs scout evidence <GOAL_ID> [--group-by method|metric|hardware|failure_mode]
cs scout summary <GOAL_ID>
cs scout synthesis <GOAL_ID> [--method METHOD] [--scout-run RUN_ID]
cs scout compare --paper <ID> --paper <ID> [--dim methods --dim results ...]   # cross-paper comparison via retrieval synthesis
```

### Ontology
```bash
cs ontology seed                    # idempotently seed default terms + method relationships
cs ontology list [--category method|metric|hardware|failure_mode|acoustic_goal|scene_assumption] [-w GOAL_ID]
cs ontology show <TERM_ID>
cs ontology add --name <NAME> --category <CAT> --keywords '["kw1","kw2"]'
cs ontology merge --source <SOURCE_ID> --target <TARGET_ID>
cs ontology derive <GOAL_ID> [--top-k 30] [--max-families 12] [--dry-run] [--pin FAMILY ...]  # induce goal-scoped method taxonomy from corpus
```

### Approaches
```bash
cs approach generate <GOAL_ID>
cs approach list <GOAL_ID> [--status generated|reviewed|scored|...] [--method <FAMILY>]
cs approach show <APPROACH_ID>
cs approach review <APPROACH_ID>
cs approach merge --source <SOURCE_ID> --target <TARGET_ID>
cs approach delete <APPROACH_ID>
```

### Critic
```bash
cs critic run <GOAL_ID> [--apply] [--yes] [--method <FAMILY>] [--json]
cs critic show <GOAL_ID> [--approach <APPROACH_ID>] [--run <CRITIQUE_RUN_ID>] [--json]
```

### Scores
```bash
cs score run <GOAL_ID> [--profile default|fastest_prototype|scientific_novelty|robustness|product_feasibility]
cs score show <APPROACH_ID>
cs score compare <GOAL_ID>
cs score pareto <GOAL_ID>
```

### Hypotheses
```bash
cs hypothesis generate <GOAL_ID> [--max N] [--no-exploratory]
cs hypothesis list <GOAL_ID> [--status generated|reviewed|...] [--type conservative|exploratory]
cs hypothesis show <HYPOTHESIS_ID>
cs hypothesis review <HYPOTHESIS_ID>
cs hypothesis delete <HYPOTHESIS_ID>
```

### Experiments
```bash
cs experiment generate <GOAL_ID> [--approach <ID>] [--hypothesis <ID>] [--max N]
cs experiment list <GOAL_ID> [--status generated|reviewed|approved|...] [--type simulation|measurement|hybrid]
cs experiment show <EXPERIMENT_ID>
cs experiment review <EXPERIMENT_ID>
cs experiment run <EXPERIMENT_ID> <GOAL_ID> [--timeout SECONDS] [--json]
cs experiment score <EXPERIMENT_ID> <GOAL_ID>
cs experiment export <EXPERIMENT_ID> [--format yaml|python]
cs experiment delete <EXPERIMENT_ID>
```

### Approval
```bash
cs approval pending [--goal <GOAL_ID>]
cs approval approve <EXPERIMENT_ID> <GOAL_ID> [--reviewer <ID>] [--reason "..."]
cs approval reject <EXPERIMENT_ID> <GOAL_ID> --reason "..."
cs approval request-edit <EXPERIMENT_ID> <GOAL_ID> --reason "..."
cs approval history <EXPERIMENT_ID> <GOAL_ID>
cs approval duplicate <EXPERIMENT_ID> <GOAL_ID>
cs approval submit <EXPERIMENT_ID> <GOAL_ID> [--mode approve_batch|approve_each_run|approval_required_above_threshold] [--approver <ID>] [--threshold <N>] [--credentialed]
cs approval retry <EXPERIMENT_ID> <GOAL_ID> [--approver <ID>]              # retry a failed handoff without duplicating RunRequests (CS-APPROVAL-010)
cs approval cancel <EXPERIMENT_ID> <GOAL_ID> [--requester <ID>] [--reason "..."]   # relay a cancellation request; records status (CS-APPROVAL-011)
cs approval resubmit <EXPERIMENT_ID> <GOAL_ID> [--requester <ID>] [--reason "..."] # relay a resubmission request; records status (CS-APPROVAL-011)
cs approval handoff-requests <EXPERIMENT_ID> <GOAL_ID>                     # list recorded handoff-control requests
```

### Validation
```bash
cs validation submit <EXPERIMENT_ID> <GOAL_ID> --metrics '{"metric": value}' [--artifacts '{"key": "path"}'] [--notes "..."]
cs validation show <EXPERIMENT_ID> <GOAL_ID>
cs validation list <GOAL_ID>
```

### Device
```bash
cs device generate <GOAL_ID> [--approach <ID>...]
cs device list <GOAL_ID> [--status generated|reviewed|superseded]
cs device show <DEVICE_ID> <GOAL_ID>
cs device review <DEVICE_ID> <GOAL_ID>
cs device compare <DEVICE_ID>... --goal <GOAL_ID>
cs device export <DEVICE_ID> <GOAL_ID> [--format markdown|json]
```

### Roadmap
```bash
cs roadmap generate <GOAL_ID>
cs roadmap list <GOAL_ID> [--lane conservative|exploratory|device_prototype] [--status open|completed|superseded]
cs roadmap show <ITEM_ID> <GOAL_ID>
cs roadmap complete <ITEM_ID> <GOAL_ID>
cs roadmap gaps <GOAL_ID>                # per-approach evidence gaps (CS-ROADMAP-003)
```

### Logs
```bash
cs logs list <GOAL_ID> [--service validation|device|roadmap] [--limit N]
cs logs show <LOG_ID> <GOAL_ID>
```

### Evaluation
```bash
cs eval approaches <GOAL_ID>    # usefulness + evidence traceability (CS-EVAL-001)
cs eval grounding <GOAL_ID>     # evidence grounding + unsupported claim rate (CS-EVAL-002)
cs eval experiments <GOAL_ID>   # acceptance rate + spec validity (CS-EVAL-003)
cs eval productivity <GOAL_ID>  # estimated time saved + satisfaction rate (CS-EVAL-005)
cs eval handoff <GOAL_ID>       # handoff success rate + retry success (CS-EVAL-007)
cs eval traceability <GOAL_ID>  # run-request traceability to research intent (CS-EVAL-008)
cs eval duplicates <GOAL_ID>    # idempotent ingestion / duplicate detection (CS-EVAL-009)
cs eval freshness <GOAL_ID>          # stale in-flight run requests (CS-EVAL-010)
cs eval failed-usefulness <GOAL_ID>  # failed-run usefulness (CS-EVAL-011)
cs eval batch-quality <GOAL_ID>      # batch aggregation quality (CS-EVAL-012)
cs eval report <GOAL_ID>        # full report as JSON
```

### Feedback
```bash
cs feedback add <GOAL_ID> <TARGET_TYPE> <TARGET_ID> [--up | --down] [--comment "..."] [--reviewer <ID>]
# TARGET_TYPE: approach|score|experiment|device|hypothesis|roadmap; default vote is --down
cs feedback list <GOAL_ID> [--type <TARGET_TYPE>] [--target <TARGET_ID>]
```

## API Endpoints

All endpoints are prefixed with `/co-scientist`.

### Goals

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals` | Create a research goal |
| GET | `/goals` | List goals (filter by status) |
| GET | `/goals/{id}` | Get goal details |
| PATCH | `/goals/{id}` | Update goal fields |
| POST | `/goals/{id}/transition` | Transition goal status |
| DELETE | `/goals/{id}` | Delete a draft goal |

### Scout

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/scout` | Run evidence retrieval |
| GET | `/goals/{id}/scout/evidence` | List evidence records |
| GET | `/goals/{id}/scout/evidence/groups` | Grouped evidence view |
| GET | `/goals/{id}/scout/evidence/summary` | Summary stats and warnings |
| GET | `/goals/{id}/scout/syntheses` | Claude per-family evidence syntheses |
| GET | `/goals/{id}/scout/evidence/{eid}` | Single evidence record |

### Approaches

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/approaches/generate` | Generate approach cards from evidence |
| POST | `/goals/{id}/approaches` | Create a manual approach card |
| GET | `/goals/{id}/approaches` | List approach cards (filter by status, method) |
| GET | `/goals/{id}/approaches/{aid}` | Get approach card details |
| GET | `/goals/{id}/approaches/{aid}/execution-evidence` | Linked experiments, bundles, validation outcomes, and provenance groups |
| PATCH | `/goals/{id}/approaches/{aid}` | Update approach card fields |
| POST | `/goals/{id}/approaches/{aid}/transition` | Transition approach status |
| DELETE | `/goals/{id}/approaches/{aid}` | Delete a generated approach |
| POST | `/goals/{id}/approaches/merge` | Merge two approach cards |
| GET | `/goals/{id}/approaches/duplicates` | Detect duplicate approach cards |

### Critic

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/critique` | Critique generated approach cards (optional `apply`) |
| GET | `/goals/{id}/critique` | List critiques (filter by approach_id, critique_run_id) |

### Scores

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/approaches/{aid}/score` | Score an approach across all dimensions |
| POST | `/goals/{id}/approaches/score-all` | Score all reviewed/scored approaches |
| GET | `/goals/{id}/approaches/{aid}/scores` | Get existing scores for an approach |
| GET | `/goals/{id}/approaches/comparison` | Ranked comparison of scored approaches |
| GET | `/goals/{id}/approaches/pareto` | Pareto frontier analysis |
| POST | `/goals/{id}/approaches/{aid}/rescore` | Rescore with different weight profile |
| GET | `/goals/{id}/score-updates` | List execution-evidence score updates (filter by `approach_id`, `experiment_id`) |

### Hypotheses

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/hypotheses/generate` | Generate hypothesis combinations from scored approaches |
| POST | `/goals/{id}/hypotheses` | Create a manual hypothesis |
| GET | `/goals/{id}/hypotheses` | List hypotheses (filter by status, type) |
| GET | `/goals/{id}/hypotheses/{hid}` | Get hypothesis details |
| PATCH | `/goals/{id}/hypotheses/{hid}` | Update hypothesis fields |
| POST | `/goals/{id}/hypotheses/{hid}/transition` | Transition hypothesis status |
| DELETE | `/goals/{id}/hypotheses/{hid}` | Delete a generated hypothesis |

### Experiments

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/experiments/generate` | Generate experiment proposals from scored approaches or hypotheses |
| POST | `/goals/{id}/experiments` | Create a manual experiment card |
| GET | `/goals/{id}/experiments` | List experiments (filter by status, type) |
| GET | `/goals/{id}/experiments/{eid}` | Get experiment card details |
| PATCH | `/goals/{id}/experiments/{eid}` | Update experiment card fields |
| POST | `/goals/{id}/experiments/{eid}/transition` | Transition experiment status |
| POST | `/goals/{id}/experiments/{eid}/score` | Score experiment against 10-dimension rubric |
| GET | `/goals/{id}/experiments/{eid}/export` | Export experiment spec as YAML or Python config |
| DELETE | `/goals/{id}/experiments/{eid}` | Delete a generated experiment |

### Approval

| Method | Path | Description |
|--------|------|-------------|
| GET | `/goals/{id}/experiments/pending` | List experiments in `reviewed` status |
| POST | `/goals/{id}/experiments/{eid}/approve` | Approve experiment (→ approved, stores YAML handoff) |
| POST | `/goals/{id}/experiments/{eid}/reject` | Reject experiment (→ superseded) |
| POST | `/goals/{id}/experiments/{eid}/request-edit` | Request edits (→ generated) |
| POST | `/goals/{id}/experiments/{eid}/duplicate` | Duplicate as editable copy |
| POST | `/goals/{id}/experiments/{eid}/submit` | Hand approved card to Experimentation System as RunRequests |
| POST | `/goals/{id}/experiments/{eid}/retry` | Retry a failed handoff without duplicating RunRequests (CS-APPROVAL-010) |
| POST | `/goals/{id}/experiments/{eid}/cancel` | Relay a cancellation request; records status (CS-APPROVAL-011) |
| POST | `/goals/{id}/experiments/{eid}/resubmit` | Relay a resubmission request; records status (CS-APPROVAL-011) |
| GET | `/goals/{id}/experiments/{eid}/handoff-requests` | List recorded handoff-control requests (CS-UI-012) |
| GET | `/goals/{id}/experiments/{eid}/decisions` | List chronological decision history |

### Validation

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/experiments/{eid}/results` | Submit measured metrics; triggers agent validation |
| GET | `/goals/{id}/experiments/{eid}/results` | Get latest validation result (404 if none) |
| GET | `/goals/{id}/experiments/results` | List all validation results for a goal |

### Device

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/devices/generate` | Generate device concepts via agent from validated approaches |
| GET | `/goals/{id}/devices` | List device concept cards (filter by status) |
| GET | `/goals/{id}/devices/compare?ids=id1,id2` | Side-by-side comparison of ≥2 concepts |
| GET | `/goals/{id}/devices/evidence-updates` | List device confidence/risk updates (filter by `device_id`) |
| GET | `/goals/{id}/devices/{did}` | Get device concept card details |
| GET | `/goals/{id}/devices/{did}/execution-evidence` | Linked experiments, validation outcomes, confidence, and affected approach scores |
| POST | `/goals/{id}/devices/{did}/transition` | Transition device concept status |
| GET | `/goals/{id}/devices/{did}/export` | Export as markdown or JSON |
| DELETE | `/goals/{id}/devices/{did}` | Delete a generated device concept |

### Roadmap

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/roadmap/generate` | Generate ranked roadmap items via agent |
| GET | `/goals/{id}/roadmap` | List roadmap items (filter by lane, status) |
| GET | `/goals/{id}/roadmap/evidence-gaps` | Per-approach evidence gaps (CS-ROADMAP-003) |
| GET | `/goals/{id}/roadmap/{rid}` | Get roadmap item details |
| POST | `/goals/{id}/roadmap/{rid}/transition` | Transition item status (open → completed \| superseded) |

### Governance

| Method | Path | Description |
|--------|------|-------------|
| GET | `/goals/{id}/agent-logs` | List agent action logs (filter by service) |
| GET | `/goals/{id}/agent-logs/{log_id}` | Get a single agent action log |
| GET | `/goals/{id}/execution-audit` | List execution audit logs (filter by `action`, `experiment_id`) |
| GET | `/goals/{id}/experiments/{experiment_id}/evidence-label` | Evidence label for an experiment (CS-GOV-012) |

Agent actions can be disabled per goal by setting `is_restricted` via `PATCH /goals/{id}` — restricted goals return 403 from all generate endpoints (validation, device, roadmap). Set `CS_ENFORCE_EXECUTION_BOUNDARY=true` to block the direct repro-runner path so experiments run only via RunRequest handoff.

### Evaluation

| Method | Path | Description |
|--------|------|-------------|
| GET | `/goals/{id}/evaluation` | Full evaluation report (all metric blocks) |
| GET | `/goals/{id}/evaluation/approach-usefulness` | Approach usefulness + traceability (CS-EVAL-001) |
| GET | `/goals/{id}/evaluation/evidence-grounding` | Evidence grounding + unsupported claim rate (CS-EVAL-002) |
| GET | `/goals/{id}/evaluation/experiment-quality` | Experiment acceptance + spec validity (CS-EVAL-003) |
| GET | `/goals/{id}/evaluation/productivity` | Estimated time saved + satisfaction rate (CS-EVAL-005) |
| GET | `/goals/{id}/evaluation/handoff-success` | Handoff success rate + retry success (CS-EVAL-007) |
| GET | `/goals/{id}/evaluation/execution-traceability` | RunRequest traceability to research intent (CS-EVAL-008) |
| GET | `/goals/{id}/evaluation/duplicate-ingestion` | Idempotent ingestion / duplicate detection (CS-EVAL-009) |
| GET | `/goals/{id}/evaluation/status-freshness` | Stale in-flight run requests (CS-EVAL-010) |
| GET | `/goals/{id}/evaluation/failed-run-usefulness` | Failed-run usefulness (CS-EVAL-011) |
| GET | `/goals/{id}/evaluation/batch-aggregation-quality` | Batch aggregation quality (CS-EVAL-012) |

### Feedback

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/feedback` | Record thumbs up/down (+ optional comment) on an artefact (CS-EVAL-006) |
| GET | `/goals/{id}/feedback` | List feedback (filter by target_type, target_id) |

### Ontology

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ontology/derive` | Derive a goal-scoped method taxonomy from the corpus (Claude-induced) |
| POST | `/ontology/terms` | Create an ontology term |
| GET | `/ontology/terms` | List terms (filter by category, status, workspace_id) |
| GET | `/ontology/terms/{id}` | Get term details |
| PATCH | `/ontology/terms/{id}` | Update term fields |
| DELETE | `/ontology/terms/{id}` | Delete a deprecated term |
| POST | `/ontology/terms/merge` | Merge source term into target |
| GET | `/ontology/terms/{id}/related` | Get related terms |
| POST | `/ontology/relationships` | Create a relationship |
| DELETE | `/ontology/relationships/{id}` | Delete a relationship |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |

## Configuration

Environment variables (prefix `CS_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `CS_DATABASE_URL` | `sqlite:///./coscientist.db` | Database connection string |
| `CS_PORT` | `8001` | API server port |
| `CS_RETRIEVAL_URL` | `http://localhost:8000` | Retrieval API base URL |
| `CS_RETRIEVAL_API_KEY` | | API key for retrieval service |
| `CS_SCOUT_TOP_K` | `20` | Results per query |
| `CS_SCOUT_STRONG_THRESHOLD` | `5` | Papers for "strong" evidence |
| `CS_SCOUT_WEAK_THRESHOLD` | `1` | Papers for "weak" evidence |
| `CS_SCOUT_SPARSE_THRESHOLD` | `3` | Warn if fewer papers than this |
| `CS_APPROACH_MIN_EVIDENCE` | `2` | Min evidence records to generate an approach |
| `CS_SCORE_WEIGHT_PROFILE` | `default` | Default weight profile (default, fastest_prototype, scientific_novelty, robustness, product_feasibility) |
| `CS_HYPOTHESIS_MAX_PER_RUN` | `20` | Max hypotheses generated per run |
| `CS_HYPOTHESIS_COMPLEMENTARY_HIGH` | `0.6` | Threshold for "high" dimension score in complementarity check |
| `CS_HYPOTHESIS_COMPLEMENTARY_LOW` | `0.4` | Threshold for "low" dimension score in complementarity check |
| `CS_EXPERIMENT_MAX_PER_RUN` | `10` | Max experiments generated per run |
| `CS_EXPERIMENT_SWEEP_COST_LOW` | `100` | Sweep cardinality at or below this → low cost/low runtime |
| `CS_EXPERIMENT_SWEEP_COST_MEDIUM` | `500` | Sweep cardinality at or below this → low cost/medium runtime |
| `CS_EXPERIMENT_SWEEP_COST_HIGH` | `2000` | Sweep cardinality at or below this → medium cost/medium runtime |
| `CS_VALIDATION_MODEL` | `claude-sonnet-4-6` | Claude model used for experiment validation agent |
| `CS_ANTHROPIC_API_KEY` | | Anthropic API key for the validation agent |
| `CS_REPRO_URL` | `http://localhost:8003` | Base URL of the repro experiment runner |
| `CS_REPRO_API_KEY` | | API key for the repro runner (sent as `x-api-key` when set) |
| `CS_EVAL_MINUTES_PER_AGENT_ACTION` | `45` | Minutes-saved heuristic per successful agent action (CS-EVAL-005) |
| `CS_EVAL_STATUS_FRESHNESS_THRESHOLD_SECONDS` | `3600` | Age after which an in-flight run request's status is stale (CS-EVAL-010) |
| `CS_ENFORCE_EXECUTION_BOUNDARY` | `false` | When true, block the direct repro-runner path — experiments run only via RunRequest handoff (CS-GOV-008) |
| `CS_SCORE_EXECUTION_DELTA` | `0.15` | Score magnitude (0..1) applied to evidence-strength on a clean pass/fail outcome (CS-SCORE-011) |
| `CS_SCORE_CONFIDENCE_DELTA` | `0.20` | Confidence magnitude (0..1) applied on execution evidence, dampened for mixed/partial outcomes (CS-SCORE-011) |
| `CS_SCORE_UPDATE_ON_PARTIAL` | `false` | When true, partial aggregations (missing runs / partial bundles) still drive approach score updates; default holds updates until the batch completes (CS-VALIDATION-012) |

## Development

```bash
# Run tests
pytest tests/ -v

# Run with auto-reload
uvicorn coscientist.main:app --reload --port 8001
```

## Project Structure

```
src/coscientist/
├── config.py              # Pydantic settings (CS_ env prefix)
├── database.py            # SQLAlchemy engine, session, Base
├── domain.py              # PSZ domain keyword dictionaries
├── main.py                # FastAPI app with lifespan
├── cli/app.py             # Typer CLI (cs goal/scout/ontology/approach commands)
├── clients/retrieval.py   # httpx client for retrieval API
├── clients/repro.py       # httpx client for the repro experiment runner (:8003)
├── models/
│   ├── goal.py            # ResearchGoal ORM
│   ├── evidence.py        # EvidenceRecord ORM
│   ├── ontology.py        # OntologyTerm, OntologyRelationship ORM
│   ├── approach.py        # ApproachCard ORM
│   ├── score.py           # RubricScore ORM
│   ├── hypothesis.py      # HypothesisCard ORM
│   ├── experiment.py      # ExperimentCard ORM
│   ├── approval.py        # ApprovalDecision ORM
│   ├── validation.py      # ValidationResult ORM
│   ├── device.py          # DeviceConceptCard ORM
│   ├── roadmap.py         # ResearchRoadmapItem ORM
│   ├── governance.py      # AgentActionLog ORM (immutable audit)
│   └── feedback.py        # Feedback ORM (thumbs up/down + comment)
├── schemas/
│   ├── goal.py            # Goal request/response schemas
│   ├── scout.py           # Scout request/response schemas
│   ├── ontology.py        # Ontology request/response schemas
│   ├── approach.py        # Approach request/response schemas
│   ├── score.py           # Score request/response schemas
│   ├── hypothesis.py      # Hypothesis request/response schemas
│   ├── experiment.py      # Experiment request/response schemas
│   ├── approval.py        # Approval request/response schemas
│   ├── validation.py      # Validation request/response schemas
│   ├── device.py          # Device concept request/response schemas
│   ├── roadmap.py         # Roadmap request/response schemas
│   ├── governance.py      # Agent action log response schemas
│   ├── evaluation.py      # Evaluation metric response schemas
│   ├── runner.py          # Runner result schema (repro integration)
│   └── feedback.py        # Feedback request/response schemas
├── services/
│   ├── goal.py            # Goal CRUD + state machine
│   ├── scout.py           # Scout orchestration + grouping
│   ├── ontology.py        # Ontology CRUD, merge, relationships
│   ├── approach.py        # Approach generation, CRUD, merge
│   ├── score.py           # Rubric scoring, comparison, Pareto
│   ├── hypothesis.py      # Hypothesis generation, compatibility, CRUD
│   ├── experiment.py      # Experiment generation, scoring, export, CRUD
│   ├── approval.py        # Approval decisions, pending queue, duplicate
│   ├── validation.py      # Agent-driven result ingestion and validation
│   ├── device.py          # Agent-driven device concept synthesis, compare, export
│   ├── roadmap.py         # Agent-driven roadmap generation, transitions, auto-retire
│   ├── governance.py      # Agent action logging, log queries, restriction checks
│   ├── evaluation.py      # Quality metrics over existing artefacts (read-only)
│   ├── runner.py          # Runs experiments on repro, translates metrics, validates
│   └── feedback.py        # Feedback capture + satisfaction counts
└── routers/
    ├── goal.py            # Goal API endpoints
    ├── scout.py           # Scout API endpoints
    ├── ontology.py        # Ontology API endpoints
    ├── approach.py        # Approach API endpoints
    ├── score.py           # Score API endpoints
    ├── hypothesis.py      # Hypothesis API endpoints
    ├── experiment.py      # Experiment API endpoints
    ├── approval.py        # Approval API endpoints
    ├── validation.py      # Validation API endpoints
    ├── device.py          # Device concept API endpoints
    ├── roadmap.py         # Roadmap API endpoints
    ├── governance.py      # Agent action log API endpoints
    ├── evaluation.py      # Evaluation metrics API endpoints
    └── feedback.py        # Feedback capture API endpoints
└── web/
    ├── routes.py          # /ui routes (thin adapter over services)
    ├── templates.py       # shared Jinja2Templates instance
    ├── templates/         # Jinja2 templates (base, pages, partials)
    └── static/app.css     # hand-written stylesheet
```
