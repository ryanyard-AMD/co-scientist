import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coscientist.clients.retrieval import (
    ChunkResult,
    MetadataFilter,
    RetrievalClient,
)
from coscientist.config import settings
from coscientist.domain import (
    METHOD_FAMILIES,
    RELATED_METHODS,
    classify_text,
    get_related_methods,
)
from coscientist.models.evidence import EvidenceRecord
from coscientist.models.ontology import OntologyTerm
from coscientist.models.synthesis import EvidenceSynthesis
from coscientist.schemas.scout import (
    AgentSynthesisOutput,
    EvidenceGroupItem,
    EvidenceGroupResponse,
    EvidenceListResponse,
    EvidenceRecordResponse,
    EvidenceStrengthEnum,
    EvidenceSynthesisResponse,
    ReportedMetric,
    ScoutResultResponse,
    ScoutRunRequest,
    ScoutSummaryStats,
    SparsityWarning,
)
from coscientist.schemas.ontology import OntologyCategoryEnum
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc
from coscientist.services import ontology as ontology_svc


def _strength(paper_count: int) -> EvidenceStrengthEnum:
    if paper_count >= settings.scout_strong_threshold:
        return EvidenceStrengthEnum.strong
    elif paper_count >= settings.scout_weak_threshold:
        return EvidenceStrengthEnum.weak
    return EvidenceStrengthEnum.none_


def _decompose_goal_to_queries(
    goal,
    method_terms: list[OntologyTerm] | None = None,
) -> list[str]:
    queries: list[str] = []
    app = goal.target_application.replace("_", " ")
    queries.append(app)
    if goal.success_criteria:
        for criterion in goal.success_criteria:
            queries.append(f"{app} {criterion.name.replace('_', ' ')}")
    if goal.device_constraints and goal.device_constraints.form_factor:
        queries.append(f"{app} {goal.device_constraints.form_factor}")
    method_names = (
        [t.canonical_name for t in method_terms]
        if method_terms is not None
        else list(METHOD_FAMILIES.keys())
    )
    for family_name in method_names:
        queries.append(f"{app} {family_name.replace('_', ' ')}")
    seen: set[str] = set()
    deduped: list[str] = []
    for q in queries:
        key = q.lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(q)
    return deduped


def _is_primary_method(
    chunk: ChunkResult,
    method_family: str,
    all_terms: list[OntologyTerm] | None = None,
) -> bool:
    if all_terms is not None:
        for t in all_terms:
            if t.canonical_name == method_family and t.category == "method":
                keywords = json.loads(t.keywords)
                break
        else:
            keywords = []
    else:
        keywords = METHOD_FAMILIES.get(method_family, [])
    text_prefix = (chunk.title + " " + chunk.text[:500]).lower()
    return any(kw in text_prefix for kw in keywords)


def _to_response(record: EvidenceRecord) -> EvidenceRecordResponse:
    return EvidenceRecordResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        scout_run_id=record.scout_run_id,
        query_text=record.query_text,
        paper_id=record.paper_id,
        title=record.title,
        year=record.year,
        section_title=record.section_title,
        page_number=record.page_number,
        chunk_id=record.chunk_id,
        chunk_index=record.chunk_index,
        chunk_text=record.chunk_text,
        score=record.score,
        vector_score=record.vector_score,
        fulltext_score=record.fulltext_score,
        method_families=json.loads(record.method_families) if record.method_families else [],
        metric_names=json.loads(record.metric_names) if record.metric_names else [],
        hardware_assumptions=json.loads(record.hardware_assumptions) if record.hardware_assumptions else [],
        failure_modes=json.loads(record.failure_modes) if record.failure_modes else [],
        is_primary_method=record.is_primary_method,
        claim_type=record.claim_type,
        confidence=record.confidence,
        evidence_strength=EvidenceStrengthEnum(record.evidence_strength),
        source_id=record.source_id,
        source_type=record.source_type,
        created_at=record.created_at,
    )


def _compute_groups_from_records(
    records: list[EvidenceRecord],
    group_by: str = "method_family",
) -> EvidenceGroupResponse:
    field_map = {
        "method_family": "method_families",
        "metric": "metric_names",
        "hardware": "hardware_assumptions",
        "failure_mode": "failure_modes",
    }
    json_field = field_map.get(group_by, "method_families")

    bucket: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for rec in records:
        raw = getattr(rec, json_field)
        keys = json.loads(raw) if raw else []
        for key in keys:
            bucket[key].append(rec)

    groups: list[EvidenceGroupItem] = []
    for key, recs in sorted(bucket.items()):
        paper_ids = {r.paper_id for r in recs}
        groups.append(EvidenceGroupItem(
            group_key=key,
            group_type=group_by,
            count=len(recs),
            paper_count=len(paper_ids),
            avg_score=sum(r.score for r in recs) / len(recs),
            evidence_strength=_strength(len(paper_ids)),
            evidence_ids=[r.id for r in recs],
        ))

    return EvidenceGroupResponse(
        groups=groups,
        total_groups=len(groups),
        total_evidence=len(records),
    )


def _assess_sparsity(
    records: list[EvidenceRecord],
    method_terms: list[OntologyTerm] | None = None,
    related_map: dict[str, list[str]] | None = None,
) -> list[SparsityWarning]:
    method_papers: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        families = json.loads(rec.method_families) if rec.method_families else []
        for mf in families:
            method_papers[mf].add(rec.paper_id)

    method_names = (
        [t.canonical_name for t in method_terms]
        if method_terms is not None
        else list(METHOD_FAMILIES.keys())
    )
    rel = related_map if related_map is not None else RELATED_METHODS

    warnings: list[SparsityWarning] = []
    for family_name in method_names:
        paper_ids = method_papers.get(family_name, set())
        count = len(paper_ids)
        if count < settings.scout_sparse_threshold:
            warnings.append(SparsityWarning(
                query_or_category=family_name,
                category_type="method_family",
                papers_found=count,
                evidence_strength=_strength(count),
                suggested_related=rel.get(family_name, []),
            ))
    return warnings


def _load_ontology_terms(db: Session):
    all_terms = list(db.scalars(
        select(OntologyTerm).where(OntologyTerm.status == "active")
    ).all())
    method_terms = [t for t in all_terms if t.category == "method"]
    from coscientist.models.ontology import OntologyRelationship
    all_rels = list(db.scalars(select(OntologyRelationship)).all())
    related_map = get_related_methods(all_terms, all_rels)
    return all_terms, method_terms, related_map


def _synthesis_to_response(row: EvidenceSynthesis) -> EvidenceSynthesisResponse:
    return EvidenceSynthesisResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        scout_run_id=row.scout_run_id,
        method_family=row.method_family,
        synthesis_text=row.synthesis_text,
        key_findings=json.loads(row.key_findings) if row.key_findings else [],
        reported_metrics=[
            ReportedMetric(**m) for m in json.loads(row.reported_metrics)
        ] if row.reported_metrics else [],
        hardware_requirements=json.loads(row.hardware_requirements) if row.hardware_requirements else [],
        failure_modes=json.loads(row.failure_modes) if row.failure_modes else [],
        open_questions=json.loads(row.open_questions) if row.open_questions else [],
        cited_evidence_ids=json.loads(row.cited_evidence_ids),
        evidence_count=row.evidence_count,
        paper_count=row.paper_count,
        model_used=row.model_used,
        created_at=row.created_at,
    )


def _run_synthesis_agent(
    db: Session,
    goal_id: str,
    method_family: str,
    records: list[EvidenceRecord],
) -> AgentSynthesisOutput:
    """Ask Claude to synthesize one method family's evidence.

    Pure RAG: the model sees only the supplied chunks and may cite only their
    evidence_ids. Citations to ids outside the supplied set are stripped by the
    caller before persistence, preserving downstream grounding integrity.
    """
    system_prompt = (
        "You are a scientific evidence synthesis agent. You are given retrieved "
        "literature chunks for ONE method family. Synthesize them into a grounded "
        "summary. You MUST respond with valid JSON only — no prose, no markdown fences. "
        "Cite ONLY the evidence_id values provided below; never invent ids. Every "
        "reported metric and finding must trace to chunks you were given. "
        "The JSON must conform to this schema:\n"
        "{\n"
        '  "synthesis_text": "<narrative grounded in the chunks>",\n'
        '  "key_findings": ["<str>", ...],\n'
        '  "reported_metrics": [{"name": "<str>", "value": "<str>", '
        '"evidence_ids": ["<id>", ...]}],\n'
        '  "hardware_requirements": ["<str>", ...],\n'
        '  "failure_modes": ["<str>", ...],\n'
        '  "open_questions": ["<str>", ...],\n'
        '  "cited_evidence_ids": ["<id>", ...]\n'
        "}\n"
        "cited_evidence_ids must list every evidence_id you relied on."
    )

    chunk_blocks = []
    for rec in records:
        chunk_blocks.append(
            f"### evidence_id: {rec.id}\n"
            f"Title: {rec.title}"
            + (f" ({rec.year})" if rec.year else "")
            + "\n"
            + (f"Section: {rec.section_title}\n" if rec.section_title else "")
            + f"Text: {rec.chunk_text[:1500]}"
        )
    user_message = (
        f"## Method family\n{method_family}\n\n"
        f"## Goal\n{goal_id}\n\n"
        f"## Evidence chunks ({len(records)})\n"
        + "\n\n".join(chunk_blocks)
        + "\n\nSynthesize the evidence above for this method family."
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    start = time.monotonic()
    message = client.messages.create(
        model=settings.validation_model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    raw_text = message.content[0].text.strip()
    governance_svc.log_agent_call(
        db=db,
        workspace_id=goal_id,
        service="scout",
        action="synthesize_evidence",
        model_used=settings.validation_model,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        elapsed_ms=elapsed_ms,
        response_summary=raw_text[:512],
    )
    try:
        parsed = json.loads(raw_text)
        return AgentSynthesisOutput(**parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Synthesis agent returned invalid JSON: {exc}",
        )


def _synthesize_groups(
    db: Session,
    goal_id: str,
    scout_run_id: str,
    records: list[EvidenceRecord],
    groups: EvidenceGroupResponse,
) -> list[EvidenceSynthesis]:
    record_by_id = {r.id: r for r in records}
    now = datetime.now(timezone.utc)
    rows: list[EvidenceSynthesis] = []

    for group in groups.groups:
        group_records = [record_by_id[eid] for eid in group.evidence_ids if eid in record_by_id]
        if not group_records:
            continue
        valid_ids = {r.id for r in group_records}

        output = _run_synthesis_agent(db, goal_id, group.group_key, group_records)

        # Grounding guard: drop any citation the model invented.
        cited = [eid for eid in output.cited_evidence_ids if eid in valid_ids]
        clean_metrics = []
        for m in output.reported_metrics:
            m.evidence_ids = [eid for eid in m.evidence_ids if eid in valid_ids]
            clean_metrics.append(m)

        row = EvidenceSynthesis(
            id=str(uuid.uuid4()),
            workspace_id=goal_id,
            scout_run_id=scout_run_id,
            method_family=group.group_key,
            synthesis_text=output.synthesis_text,
            key_findings=json.dumps(output.key_findings),
            reported_metrics=json.dumps([m.model_dump() for m in clean_metrics]),
            hardware_requirements=json.dumps(output.hardware_requirements),
            failure_modes=json.dumps(output.failure_modes),
            open_questions=json.dumps(output.open_questions),
            cited_evidence_ids=json.dumps(cited),
            evidence_count=len(group_records),
            paper_count=group.paper_count,
            model_used=settings.validation_model,
            created_at=now,
        )
        db.add(row)
        rows.append(row)

    db.commit()
    return rows


def run_scout(
    db: Session,
    goal_id: str,
    request: ScoutRunRequest,
    retrieval_client: RetrievalClient | None = None,
) -> ScoutResultResponse:
    goal = goal_svc.get(db, goal_id)

    # Load ontology terms from DB (falls back gracefully if tables empty)
    all_terms, method_terms, related_map = _load_ontology_terms(db)
    use_db_terms = len(all_terms) > 0

    queries = _decompose_goal_to_queries(
        goal,
        method_terms=method_terms if use_db_terms else None,
    )
    if request.method_families:
        for mf in request.method_families:
            q = f"{goal.target_application.replace('_', ' ')} {mf.replace('_', ' ')}"
            if q not in queries:
                queries.append(q)

    metadata_filter: MetadataFilter | None = None
    if request.filters:
        metadata_filter = MetadataFilter(
            year_min=request.filters.year_min,
            year_max=request.filters.year_max,
            authors=request.filters.authors,
            source_collection=request.filters.source_collection,
            source_tag=request.filters.source_tag,
        )

    scout_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    client = retrieval_client or RetrievalClient()
    all_records: list[EvidenceRecord] = []
    seen_chunk_ids: set[str] = set()

    try:
        for query_text in queries:
            try:
                qr = client.query_with_filters(
                    query_text,
                    top_k=request.top_k,
                    filters=metadata_filter,
                    generate_answer=False,
                )
            except Exception:
                continue

            for chunk in qr.results:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk.chunk_id)

                classification = classify_text(
                    chunk.text,
                    terms=all_terms if use_db_terms else None,
                )

                if request.method_families:
                    chunk_methods = set(classification["method_families"])
                    requested = set(request.method_families)
                    if not chunk_methods & requested:
                        text_lower = chunk.text.lower()
                        if not any(mf.replace("_", " ") in text_lower for mf in request.method_families):
                            continue

                primary = any(
                    _is_primary_method(chunk, mf, all_terms if use_db_terms else None)
                    for mf in classification["method_families"]
                )

                record = EvidenceRecord(
                    id=str(uuid.uuid4()),
                    workspace_id=goal.workspace_id,
                    scout_run_id=scout_run_id,
                    query_text=query_text,
                    paper_id=chunk.paper_id,
                    title=chunk.title,
                    year=None,
                    section_title=chunk.section_title,
                    page_number=chunk.page_number,
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.text,
                    score=chunk.score,
                    vector_score=chunk.vector_score,
                    fulltext_score=chunk.fulltext_score,
                    method_families=json.dumps(classification["method_families"]),
                    metric_names=json.dumps(classification["metrics"]),
                    hardware_assumptions=json.dumps(classification["hardware"]),
                    failure_modes=json.dumps(classification["failure_modes"]),
                    is_primary_method=primary,
                    claim_type=None,
                    confidence=None,
                    evidence_strength="none",
                    source_id=chunk.source_id,
                    source_type=chunk.source_type,
                    created_at=now,
                )
                all_records.append(record)

        _enrich_paper_metadata(all_records, client)
    finally:
        if retrieval_client is None:
            client.close()

    groups = _compute_groups_from_records(all_records, "method_family")

    strength_by_paper: dict[str, str] = {}
    for g in groups.groups:
        for rec in all_records:
            if rec.id in g.evidence_ids:
                current = strength_by_paper.get(rec.paper_id, "none")
                if _strength_rank(g.evidence_strength.value) > _strength_rank(current):
                    strength_by_paper[rec.paper_id] = g.evidence_strength.value

    for rec in all_records:
        rec.evidence_strength = strength_by_paper.get(rec.paper_id, "none")

    warnings = _assess_sparsity(
        all_records,
        method_terms=method_terms if use_db_terms else None,
        related_map=related_map if use_db_terms else None,
    )

    for record in all_records:
        db.add(record)
    db.commit()

    all_papers = {r.paper_id for r in all_records}
    all_methods: set[str] = set()
    strong_count = weak_count = no_count = 0
    for g in groups.groups:
        all_methods.add(g.group_key)
        if g.evidence_strength == EvidenceStrengthEnum.strong:
            strong_count += 1
        elif g.evidence_strength == EvidenceStrengthEnum.weak:
            weak_count += 1
        else:
            no_count += 1

    summary = ScoutSummaryStats(
        scout_run_id=scout_run_id,
        goal_id=goal_id,
        total_evidence=len(all_records),
        total_papers=len(all_papers),
        total_queries=len(queries),
        queries_executed=queries,
        method_families_found=sorted(all_methods),
        strong_evidence_count=strong_count,
        weak_evidence_count=weak_count,
        no_evidence_count=no_count,
        warnings=warnings,
    )

    syntheses: list[EvidenceSynthesisResponse] = []
    if request.synthesize and settings.anthropic_api_key and all_records:
        rows = _synthesize_groups(db, goal_id, scout_run_id, all_records, groups)
        syntheses = [_synthesis_to_response(r) for r in rows]

    return ScoutResultResponse(
        scout_run_id=scout_run_id,
        goal_id=goal_id,
        evidence_count=len(all_records),
        groups=groups,
        summary=summary,
        syntheses=syntheses,
    )


def _strength_rank(s: str) -> int:
    return {"none": 0, "weak": 1, "strong": 2}.get(s, 0)


def _enrich_paper_metadata(
    records: list[EvidenceRecord],
    client: RetrievalClient,
) -> None:
    unique_papers = {r.paper_id for r in records}
    cache: dict[str, int | None] = {}
    for paper_id in unique_papers:
        try:
            meta = client.get_document(paper_id)
            cache[paper_id] = meta.year
        except Exception:
            continue
    for rec in records:
        if rec.paper_id in cache:
            rec.year = cache[rec.paper_id]


def get_evidence(
    db: Session,
    goal_id: str,
    *,
    scout_run_id: str | None = None,
    method_family: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[EvidenceRecordResponse], int]:
    goal_svc.get(db, goal_id)

    q = select(EvidenceRecord).where(EvidenceRecord.workspace_id == goal_id)
    if scout_run_id:
        q = q.where(EvidenceRecord.scout_run_id == scout_run_id)
    if method_family:
        q = q.where(EvidenceRecord.method_families.contains(f'"{method_family}"'))

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(EvidenceRecord.score.desc()).offset(skip).limit(limit)).all()
    return [_to_response(r) for r in rows], total or 0


def get_evidence_by_id(
    db: Session,
    goal_id: str,
    evidence_id: str,
) -> EvidenceRecordResponse:
    goal_svc.get(db, goal_id)

    record = db.get(EvidenceRecord, evidence_id)
    if record is None or record.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Evidence {evidence_id!r} not found")
    return _to_response(record)


def get_syntheses(
    db: Session,
    goal_id: str,
    *,
    scout_run_id: str | None = None,
    method_family: str | None = None,
) -> list[EvidenceSynthesisResponse]:
    goal_svc.get(db, goal_id)

    q = select(EvidenceSynthesis).where(EvidenceSynthesis.workspace_id == goal_id)
    if scout_run_id:
        q = q.where(EvidenceSynthesis.scout_run_id == scout_run_id)
    if method_family:
        q = q.where(EvidenceSynthesis.method_family == method_family)
    rows = db.scalars(q.order_by(EvidenceSynthesis.method_family)).all()
    return [_synthesis_to_response(r) for r in rows]


def get_evidence_groups(
    db: Session,
    goal_id: str,
    *,
    group_by: str = "method_family",
    scout_run_id: str | None = None,
) -> EvidenceGroupResponse:
    goal_svc.get(db, goal_id)

    q = select(EvidenceRecord).where(EvidenceRecord.workspace_id == goal_id)
    if scout_run_id:
        q = q.where(EvidenceRecord.scout_run_id == scout_run_id)
    records = list(db.scalars(q).all())
    return _compute_groups_from_records(records, group_by)


def get_summary(
    db: Session,
    goal_id: str,
    scout_run_id: str | None = None,
) -> ScoutSummaryStats:
    goal_svc.get(db, goal_id)

    q = select(EvidenceRecord).where(EvidenceRecord.workspace_id == goal_id)
    if scout_run_id:
        q = q.where(EvidenceRecord.scout_run_id == scout_run_id)
    records = list(db.scalars(q).all())

    if not records:
        return ScoutSummaryStats(
            scout_run_id=scout_run_id or "",
            goal_id=goal_id,
            total_evidence=0,
            total_papers=0,
            total_queries=0,
            queries_executed=[],
            method_families_found=[],
            strong_evidence_count=0,
            weak_evidence_count=0,
            no_evidence_count=0,
            warnings=[],
        )

    run_id = scout_run_id or records[0].scout_run_id
    all_papers = {r.paper_id for r in records}
    all_queries = list(dict.fromkeys(r.query_text for r in records))

    groups = _compute_groups_from_records(records, "method_family")
    warnings = _assess_sparsity(records)

    all_methods: set[str] = set()
    strong = weak = no_ = 0
    for g in groups.groups:
        all_methods.add(g.group_key)
        if g.evidence_strength == EvidenceStrengthEnum.strong:
            strong += 1
        elif g.evidence_strength == EvidenceStrengthEnum.weak:
            weak += 1
        else:
            no_ += 1

    return ScoutSummaryStats(
        scout_run_id=run_id,
        goal_id=goal_id,
        total_evidence=len(records),
        total_papers=len(all_papers),
        total_queries=len(all_queries),
        queries_executed=all_queries,
        method_families_found=sorted(all_methods),
        strong_evidence_count=strong,
        weak_evidence_count=weak,
        no_evidence_count=no_,
        warnings=warnings,
    )
