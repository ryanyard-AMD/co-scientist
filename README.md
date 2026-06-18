# Co-Scientist: Agent-Based Research-to-Device Synthesis

An agent-based co-scientist system that accelerates research-to-device synthesis for personal sound zones. Sits above the [Research Paper Knowledge Retrieval System](https://github.com/ryanyard-AMD/retrieval) and [Reproducible Research Experimentation Environment](https://github.com/ryanyard-AMD/experiment) to convert literature into structured approach candidates, score them, generate experiments, and propose device architectures.

## Architecture

```
Layer 4: Co-Scientist (this project, port 8001)
         ├── Goal Workspace    (CS-EPIC-GOAL)
         ├── Research Scout     (CS-EPIC-SCOUT)
         ├── Approach Forge     (CS-EPIC-APPROACH)
         ├── Rubric Scoring     (CS-EPIC-SCORE)
         ├── Hypothesis Gen    (CS-EPIC-HYPOTHESIS)
         ├── Experiment Design  (CS-EPIC-EXPERIMENT)
         ├── Human Approval     (CS-EPIC-APPROVAL)
         └── Device Synthesis   (CS-EPIC-DEVICE)     [planned]
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

### CS-EPIC-ONTOLOGY: PSZ Semantic Layer

Database-backed taxonomy for personal sound zone domain concepts, replacing hardcoded keyword dictionaries.

- **OntologyTerm** with 6 categories: method, metric, hardware, failure_mode, acoustic_goal, scene_assumption
- **OntologyRelationship** for term-to-term links (related_to, subsumes, alias_of)
- 63 seed terms across all categories, seeded via Alembic migration
- CRUD API + merge operation (merges keywords, moves relationships, updates evidence records, deprecates source)
- Scout automatically loads ontology terms from DB for classification

### CS-EPIC-APPROACH: Approach Card Generation and Curation

Synthesizes scout evidence into structured Approach Cards — one per method family — for comparing candidate research approaches.

- **ApproachCard** with 8-state lifecycle: `generated` → `reviewed` → `scored` → `experiment_proposed` → `tested` → `validated` / `refuted` → `superseded`
- Algorithmic generation from evidence groups: extracts metrics, hardware requirements, risks, and evidence links per method family
- Every field traced to source evidence records with direct/inferred evidence type
- Duplicate detection across approach cards within a workspace
- Merge operation combines evidence, metrics, hardware, risks; supersedes source card
- Maturity inference (theoretical, simulated, measured, validated) from evidence text

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

### CS-EPIC-HYPOTHESIS: Hypothesis and Combination Generation

Generates HypothesisCards — proposed combinations of 2+ scored approaches — with compatibility analysis, rationale, and testability artifacts.

- **HypothesisCard** with 4-state lifecycle: `generated` → `reviewed` → `experiment_proposed` → `superseded`
- Two hypothesis types: `conservative` (both high-scoring, no conflicts) and `exploratory` (complementary strengths, may have flagged conflicts)
- Pairwise compatibility analysis: shared hardware, conflicting assumptions, complementary rubric dimensions, ontology relationships
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
cs scout summary <GOAL_ID>          # check evidence counts and sparsity warnings
cs scout evidence <GOAL_ID> --group-by method   # review method families found
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

## Command Reference

### Goals
```bash
cs goal create --name <NAME> --app <APP>
cs goal list [--status draft|active|archived]
cs goal show <GOAL_ID>
cs goal activate <GOAL_ID>
cs goal archive <GOAL_ID>
cs goal delete <GOAL_ID>
```

### Scout
```bash
cs scout run <GOAL_ID>
cs scout evidence <GOAL_ID> [--group-by method|metric|hardware|failure_mode]
cs scout summary <GOAL_ID>
```

### Ontology
```bash
cs ontology list [--category method|metric|hardware|failure_mode|acoustic_goal|scene_assumption]
cs ontology show <TERM_ID>
cs ontology add --name <NAME> --category <CAT> --keywords '["kw1","kw2"]'
cs ontology merge --source <SOURCE_ID> --target <TARGET_ID>
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
| GET | `/goals/{id}/scout/evidence/{eid}` | Single evidence record |

### Approaches

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/approaches/generate` | Generate approach cards from evidence |
| POST | `/goals/{id}/approaches` | Create a manual approach card |
| GET | `/goals/{id}/approaches` | List approach cards (filter by status, method) |
| GET | `/goals/{id}/approaches/{aid}` | Get approach card details |
| PATCH | `/goals/{id}/approaches/{aid}` | Update approach card fields |
| POST | `/goals/{id}/approaches/{aid}/transition` | Transition approach status |
| DELETE | `/goals/{id}/approaches/{aid}` | Delete a generated approach |
| POST | `/goals/{id}/approaches/merge` | Merge two approach cards |
| GET | `/goals/{id}/approaches/duplicates` | Detect duplicate approach cards |

### Scores

| Method | Path | Description |
|--------|------|-------------|
| POST | `/goals/{id}/approaches/{aid}/score` | Score an approach across all dimensions |
| POST | `/goals/{id}/approaches/score-all` | Score all reviewed/scored approaches |
| GET | `/goals/{id}/approaches/{aid}/scores` | Get existing scores for an approach |
| GET | `/goals/{id}/approaches/comparison` | Ranked comparison of scored approaches |
| GET | `/goals/{id}/approaches/pareto` | Pareto frontier analysis |
| POST | `/goals/{id}/approaches/{aid}/rescore` | Rescore with different weight profile |

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
| GET | `/goals/{id}/experiments/{eid}/decisions` | List chronological decision history |

### Ontology

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ontology/terms` | Create an ontology term |
| GET | `/ontology/terms` | List terms (filter by category, status) |
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
├── models/
│   ├── goal.py            # ResearchGoal ORM
│   ├── evidence.py        # EvidenceRecord ORM
│   ├── ontology.py        # OntologyTerm, OntologyRelationship ORM
│   ├── approach.py        # ApproachCard ORM
│   ├── score.py           # RubricScore ORM
│   ├── hypothesis.py      # HypothesisCard ORM
│   ├── experiment.py      # ExperimentCard ORM
│   └── approval.py        # ApprovalDecision ORM
├── schemas/
│   ├── goal.py            # Goal request/response schemas
│   ├── scout.py           # Scout request/response schemas
│   ├── ontology.py        # Ontology request/response schemas
│   ├── approach.py        # Approach request/response schemas
│   ├── score.py           # Score request/response schemas
│   ├── hypothesis.py      # Hypothesis request/response schemas
│   ├── experiment.py      # Experiment request/response schemas
│   └── approval.py        # Approval request/response schemas
├── services/
│   ├── goal.py            # Goal CRUD + state machine
│   ├── scout.py           # Scout orchestration + grouping
│   ├── ontology.py        # Ontology CRUD, merge, relationships
│   ├── approach.py        # Approach generation, CRUD, merge
│   ├── score.py           # Rubric scoring, comparison, Pareto
│   ├── hypothesis.py      # Hypothesis generation, compatibility, CRUD
│   ├── experiment.py      # Experiment generation, scoring, export, CRUD
│   └── approval.py        # Approval decisions, pending queue, duplicate
└── routers/
    ├── goal.py            # Goal API endpoints
    ├── scout.py           # Scout API endpoints
    ├── ontology.py        # Ontology API endpoints
    ├── approach.py        # Approach API endpoints
    ├── score.py           # Score API endpoints
    ├── hypothesis.py      # Hypothesis API endpoints
    ├── experiment.py      # Experiment API endpoints
    └── approval.py        # Approval API endpoints
```
