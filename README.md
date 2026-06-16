# Co-Scientist: Agent-Based Research-to-Device Synthesis

An agent-based co-scientist system that accelerates research-to-device synthesis for personal sound zones. Sits above the [Research Paper Knowledge Retrieval System](https://github.com/ryanyard-AMD/retrieval) and [Reproducible Research Experimentation Environment](https://github.com/ryanyard-AMD/experiment) to convert literature into structured approach candidates, score them, generate experiments, and propose device architectures.

## Architecture

```
Layer 4: Co-Scientist (this project, port 8001)
         ├── Goal Workspace    (CS-EPIC-GOAL)
         ├── Research Scout     (CS-EPIC-SCOUT)
         ├── Approach Forge     (CS-EPIC-FORGE)     [planned]
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
├── cli/app.py             # Typer CLI (cs goal/scout commands)
├── clients/retrieval.py   # httpx client for retrieval API
├── models/
│   ├── goal.py            # ResearchGoal ORM
│   ├── evidence.py        # EvidenceRecord ORM
│   └── ontology.py        # OntologyTerm, OntologyRelationship ORM
├── schemas/
│   ├── goal.py            # Goal request/response schemas
│   ├── scout.py           # Scout request/response schemas
│   └── ontology.py        # Ontology request/response schemas
├── services/
│   ├── goal.py            # Goal CRUD + state machine
│   ├── scout.py           # Scout orchestration + grouping
│   └── ontology.py        # Ontology CRUD, merge, relationships
└── routers/
    ├── goal.py            # Goal API endpoints
    ├── scout.py           # Scout API endpoints
    └── ontology.py        # Ontology API endpoints
```
