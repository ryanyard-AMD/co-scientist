# Co-Scientist: Agent-Based Research-to-Device Synthesis

An agent-based co-scientist system that accelerates research-to-device synthesis for personal sound zones. Sits above the [Research Paper Knowledge Retrieval System](https://github.com/ryanyard-AMD/retrieval) and [Reproducible Research Experimentation Environment](https://github.com/ryanyard-AMD/experiment) to convert literature into structured approach candidates, score them, generate experiments, and propose device architectures.

## Architecture

```
Layer 4: Co-Scientist (this project, port 8001)
         ├── Goal Workspace    (CS-EPIC-GOAL)
         ├── Research Scout     (CS-EPIC-SCOUT)
         ├── Approach Forge     (CS-EPIC-APPROACH)
         ├── Rubric Scoring     (CS-EPIC-SCORE)
         ├── Experiment Design  (CS-EPIC-EXPERIMENT) [planned]
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

## Quick Start

```bash
# Prerequisites: Python 3.12, uv
uv venv && uv pip install -e ".[dev]"
alembic upgrade head

# Start the API
uvicorn coscientist.main:app --reload --port 8001

# Or use the CLI
cs goal create --name "PSZ Headphone" --app personal_sound_zones
cs goal list
cs goal activate <GOAL_ID>

# Run scout (requires retrieval API on port 8000)
cs scout run <GOAL_ID>
cs scout evidence <GOAL_ID> --group-by method
cs scout summary <GOAL_ID>

# Browse ontology
cs ontology list --category method
cs ontology show <TERM_ID>
cs ontology add --name "new_method" --category method --keywords '["new method"]'
cs ontology merge --source <SOURCE_ID> --target <TARGET_ID>

# Generate and manage approach cards
cs approach generate <GOAL_ID>
cs approach list <GOAL_ID>
cs approach show <APPROACH_ID>
cs approach review <APPROACH_ID>
cs approach merge --source <SOURCE_ID> --target <TARGET_ID>

# Score and compare approaches
cs score run <GOAL_ID>                          # score all reviewed approaches
cs score run <GOAL_ID> --profile robustness     # score with alternate weight profile
cs score show <APPROACH_ID>                     # show dimension scores
cs score compare <GOAL_ID>                      # ranked comparison table
cs score pareto <GOAL_ID>                       # Pareto-optimal set
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
│   └── score.py           # RubricScore ORM
├── schemas/
│   ├── goal.py            # Goal request/response schemas
│   ├── scout.py           # Scout request/response schemas
│   ├── ontology.py        # Ontology request/response schemas
│   ├── approach.py        # Approach request/response schemas
│   └── score.py           # Score request/response schemas
├── services/
│   ├── goal.py            # Goal CRUD + state machine
│   ├── scout.py           # Scout orchestration + grouping
│   ├── ontology.py        # Ontology CRUD, merge, relationships
│   ├── approach.py        # Approach generation, CRUD, merge
│   └── score.py           # Rubric scoring, comparison, Pareto
└── routers/
    ├── goal.py            # Goal API endpoints
    ├── scout.py           # Scout API endpoints
    ├── ontology.py        # Ontology API endpoints
    ├── approach.py        # Approach API endpoints
    └── score.py           # Score API endpoints
```
