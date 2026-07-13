"""Corpus-derived, goal-scoped method-family taxonomy induction.

Instead of forcing every goal into the static 7 `METHOD_FAMILIES`, this samples
the retrieval corpus for a goal, asks Claude to induce the method families
actually present, and persists them as goal-scoped OntologyTerms (workspace_id ==
goal_id). Scout then loads those in place of the global seed for that goal.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from coscientist.clients.retrieval import RetrievalClient
from coscientist.config import settings
from coscientist.models.ontology import OntologyRelationship, OntologyTerm
from coscientist.schemas.taxonomy import (
    RECORD_TAXONOMY_TOOL,
    AgentTaxonomyOutput,
    InducedFamily,
    TaxonomyDeriveResult,
)
from coscientist.schemas.goal import GoalUpdate
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc

_MAX_SAMPLE_CHUNKS = 120
_SNIPPET_CHARS = 800
_NAME_RE = re.compile(r"[^a-z0-9]+")
# Bound the entity fan-out so grounding never dominates derivation latency.
_MAX_HINT_PAPERS = 15
_MAX_METHOD_HINTS = 40


def _canonicalize(name: str) -> str:
    return _NAME_RE.sub("_", name.strip().lower()).strip("_")


def _build_sampling_queries(goal) -> list[str]:
    """Broad, family-agnostic queries — deliberately NOT keyed on any fixed
    taxonomy, so the corpus (not our priors) determines what surfaces."""
    app = goal.target_application.replace("_", " ")
    queries: list[str] = [app]
    if goal.description:
        queries.append(goal.description[:300])
    for criterion in goal.success_criteria or []:
        queries.append(f"{app} {criterion.name.replace('_', ' ')}")
    dc = goal.device_constraints
    if dc and dc.form_factor:
        queries.append(f"{app} {dc.form_factor.replace('_', ' ')}")
    seen: set[str] = set()
    deduped: list[str] = []
    for q in queries:
        key = q.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(q)
    return deduped


def _sample_corpus(goal, top_k: int, client: RetrievalClient) -> list:
    chunks: list = []
    seen_chunk_ids: set[str] = set()
    for query_text in _build_sampling_queries(goal):
        try:
            qr = client.query_with_filters(
                query_text, top_k=top_k, generate_answer=False
            )
        except Exception:
            continue
        for chunk in qr.results:
            if chunk.chunk_id in seen_chunk_ids:
                continue
            if chunk.score <= settings.scout_min_score:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            chunks.append(chunk)
            if len(chunks) >= _MAX_SAMPLE_CHUNKS:
                return chunks
    return chunks


def _gather_corpus_hints(client: RetrievalClient, chunks: list) -> tuple[list[str], list[str]]:
    """Pull GraphRAG grounding for taxonomy induction: Method entity nodes from
    the sampled papers, plus (optionally) whole-corpus topic clusters. Both are
    best-effort — failures degrade to no hint rather than blocking derivation."""
    method_names: list[str] = []
    if settings.taxonomy_ground_in_corpus:
        seen_papers: set[str] = set()
        seen_methods: set[str] = set()
        for chunk in chunks:
            pid = chunk.paper_id
            if pid in seen_papers:
                continue
            seen_papers.add(pid)
            if len(seen_papers) > _MAX_HINT_PAPERS:
                break
            try:
                ents = client.get_paper_entities(pid)
            except Exception:
                continue
            for method in (ents.get("methods") or []):
                name = (method.get("name") or "").strip()
                key = name.lower()
                if name and key not in seen_methods:
                    seen_methods.add(key)
                    method_names.append(name)
            if len(method_names) >= _MAX_METHOD_HINTS:
                method_names = method_names[:_MAX_METHOD_HINTS]
                break

    cluster_hints: list[str] = []
    if settings.taxonomy_use_topic_clusters:
        try:
            clusters = client.list_topic_clusters(
                k=settings.taxonomy_cluster_k,
                timeout=settings.taxonomy_cluster_timeout,
            )
        except Exception:
            clusters = []
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            terms = cluster.get("terms") or cluster.get("keywords") or cluster.get("top_terms")
            if isinstance(terms, list) and terms:
                cluster_hints.append(", ".join(str(t) for t in terms[:6]))
                continue
            label = cluster.get("label") or cluster.get("topic") or cluster.get("name")
            if label:
                cluster_hints.append(str(label))
    return method_names, cluster_hints


def _induce_taxonomy(
    db: Session,
    goal,
    chunks: list,
    max_families: int,
    pinned: list[str] | None = None,
    method_hints: list[str] | None = None,
    cluster_hints: list[str] | None = None,
) -> AgentTaxonomyOutput:
    system_prompt = (
        "You are a scientific taxonomy induction agent. You are given retrieved "
        "literature chunks for ONE research goal. Identify the distinct METHOD "
        "FAMILIES (technical approaches/techniques) that are actually present in "
        "these chunks and relevant to the goal, and record them by calling the "
        "record_taxonomy tool. Ground every family in the supplied text: "
        "canonical_name must be snake_case; keywords must be lowercase surface "
        f"forms that literally appear in the chunks. Return at most {max_families} "
        "families, favouring the families most represented and most relevant to "
        "the goal. Do not invent families that are not supported by the chunks."
    )
    if pinned:
        pinned_list = ", ".join(pinned)
        system_prompt += (
            f" The following method families are DEFINING technologies for this "
            f"goal and MUST appear in your output, each with the exact snake_case "
            f"canonical_name given: {pinned_list}. Ground their keywords and "
            f"related_to in the chunks; if a pinned family is only weakly present, "
            f"still include it with the best supporting surface forms you can find. "
            f"Induce the remaining families from the corpus to fill the rest of the "
            f"{max_families}-family budget."
        )
    if method_hints:
        hint_list = ", ".join(method_hints)
        system_prompt += (
            " The corpus GraphRAG index already extracted these METHOD entity nodes "
            f"from the sampled papers (Title Case surface forms): {hint_list}. When a "
            "family you induce corresponds to one of these nodes, align its "
            "canonical_name to the node (snake_cased) so the taxonomy reconciles with "
            "the corpus graph. Treat these as grounding hints, not a required output "
            "set — only include families actually supported by the chunks."
        )
    if cluster_hints:
        cluster_list = "; ".join(cluster_hints)
        system_prompt += (
            " Embedding-based topic clusters over the whole corpus (noisy, may include "
            f"off-domain papers) suggest these groupings: {cluster_list}. Use only as "
            "weak hints."
        )
    chunk_blocks = []
    for chunk in chunks:
        block = f"Title: {chunk.title}"
        if getattr(chunk, "section_title", None):
            block += f"\nSection: {chunk.section_title}"
        block += f"\nText: {chunk.text[:_SNIPPET_CHARS]}"
        chunk_blocks.append(block)

    criteria = ", ".join(c.name for c in (goal.success_criteria or []))
    user_message = (
        f"## Research goal\n{goal.name}\n\n"
        f"## Description\n{goal.description or '(none)'}\n\n"
        f"## Success criteria\n{criteria or '(none)'}\n\n"
        f"## Corpus chunks ({len(chunks)})\n"
        + "\n\n".join(chunk_blocks)
        + "\n\nInduce the method-family taxonomy present in the corpus above."
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    start = time.monotonic()
    message = client.messages.create(
        model=settings.validation_model,
        max_tokens=4096,
        system=system_prompt,
        tools=[RECORD_TAXONOMY_TOOL],
        tool_choice={"type": "tool", "name": "record_taxonomy"},
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    tool_use = next((b for b in message.content if b.type == "tool_use"), None)
    governance_svc.log_agent_call(
        db=db,
        workspace_id=goal.workspace_id,
        service="taxonomy",
        action="derive_taxonomy",
        model_used=settings.validation_model,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        elapsed_ms=elapsed_ms,
        response_summary=(json.dumps(tool_use.input)[:512] if tool_use else "no tool_use block"),
    )
    if tool_use is None:
        raise HTTPException(
            status_code=502,
            detail="Taxonomy agent did not return a record_taxonomy tool call",
        )
    try:
        return AgentTaxonomyOutput(**tool_use.input)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Taxonomy agent returned invalid output: {exc}",
        )


def _normalize_families(
    raw: list[InducedFamily], max_families: int, pinned: list[str] | None = None
) -> list[InducedFamily]:
    pinned_canon = [_canonicalize(p) for p in (pinned or []) if p.strip()]
    pinned_set = set(pinned_canon)

    by_name: dict[str, InducedFamily] = {}
    order: list[InducedFamily] = []
    for fam in raw:
        canon = _canonicalize(fam.canonical_name)
        if not canon or canon in by_name:
            continue
        keywords = list(dict.fromkeys(k.strip().lower() for k in fam.keywords if k.strip()))
        if not keywords:
            keywords = [canon.replace("_", " ")]
        norm = InducedFamily(
            canonical_name=canon,
            description=fam.description,
            keywords=keywords,
            related_to=[_canonicalize(r) for r in fam.related_to if r.strip()],
        )
        by_name[canon] = norm
        order.append(norm)

    # Guarantee every pinned family is present, even if the agent dropped it.
    for canon in pinned_canon:
        if canon not in by_name:
            norm = InducedFamily(
                canonical_name=canon,
                description=None,
                keywords=[canon.replace("_", " ")],
                related_to=[],
            )
            by_name[canon] = norm
            order.append(norm)

    # Pins first (declared order), then corpus families; pins never truncated.
    pinned_families = [by_name[c] for c in pinned_canon]
    rest = [f for f in order if f.canonical_name not in pinned_set]
    remaining = max(0, max_families - len(pinned_families))
    families = pinned_families + rest[:remaining]

    # Drop related_to references to names not in the final set.
    names = {f.canonical_name for f in families}
    for fam in families:
        fam.related_to = [r for r in fam.related_to if r in names and r != fam.canonical_name]
    return families


def _clear_goal_scoped_methods(db: Session, workspace_id: str) -> None:
    existing = list(db.scalars(
        select(OntologyTerm).where(
            OntologyTerm.category == "method",
            OntologyTerm.workspace_id == workspace_id,
        )
    ).all())
    if not existing:
        return
    ids = {t.id for t in existing}
    rels = db.scalars(
        select(OntologyRelationship).where(
            or_(
                OntologyRelationship.source_term_id.in_(ids),
                OntologyRelationship.target_term_id.in_(ids),
            )
        )
    ).all()
    for rel in rels:
        db.delete(rel)
    for term in existing:
        db.delete(term)


def _persist(db: Session, workspace_id: str, families: list[InducedFamily]) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    _clear_goal_scoped_methods(db, workspace_id)
    db.flush()

    name_to_id: dict[str, str] = {}
    for fam in families:
        term = OntologyTerm(
            id=str(uuid.uuid4()),
            canonical_name=fam.canonical_name,
            category="method",
            description=fam.description,
            keywords=json.dumps(fam.keywords),
            status="active",
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )
        db.add(term)
        name_to_id[fam.canonical_name] = term.id
    db.flush()

    rels_added = 0
    seen_pairs: set[tuple[str, str]] = set()
    for fam in families:
        src_id = name_to_id[fam.canonical_name]
        for target in fam.related_to:
            tgt_id = name_to_id.get(target)
            if not tgt_id or (src_id, tgt_id) in seen_pairs:
                continue
            db.add(OntologyRelationship(
                id=str(uuid.uuid4()),
                source_term_id=src_id,
                target_term_id=tgt_id,
                relationship_type="related_to",
                created_at=now,
            ))
            seen_pairs.add((src_id, tgt_id))
            rels_added += 1
    db.commit()
    return len(families), rels_added


def derive_taxonomy(
    db: Session,
    goal_id: str,
    *,
    top_k: int = 30,
    max_families: int = 12,
    dry_run: bool = False,
    pinned: list[str] | None = None,
    retrieval_client: RetrievalClient | None = None,
) -> TaxonomyDeriveResult:
    goal = goal_svc.get(db, goal_id)

    # Effective pins = the goal's declared must-haves plus any ad-hoc override.
    effective_pins: list[str] = []
    for name in list(goal.pinned_method_families or []) + list(pinned or []):
        canon = _canonicalize(name)
        if canon and canon not in effective_pins:
            effective_pins.append(canon)

    client = retrieval_client or RetrievalClient()
    method_hints: list[str] = []
    cluster_hints: list[str] = []
    try:
        chunks = _sample_corpus(goal, top_k, client)
        if chunks:
            method_hints, cluster_hints = _gather_corpus_hints(client, chunks)
    finally:
        if retrieval_client is None:
            client.close()

    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="Corpus sampling returned no chunks; cannot derive a taxonomy.",
        )

    raw = _induce_taxonomy(
        db, goal, chunks, max_families, effective_pins,
        method_hints=method_hints, cluster_hints=cluster_hints,
    )
    families = _normalize_families(raw.families, max_families, effective_pins)
    if not families:
        raise HTTPException(
            status_code=502,
            detail="Taxonomy agent returned no usable families.",
        )

    papers = len({c.paper_id for c in chunks})
    if dry_run:
        return TaxonomyDeriveResult(
            goal_id=goal_id,
            workspace_id=goal.workspace_id,
            dry_run=True,
            chunks_sampled=len(chunks),
            papers_sampled=papers,
            families=families,
            terms_created=0,
            relationships_created=0,
        )

    terms_created, rels_created = _persist(db, goal.workspace_id, families)

    # The CLI documents --pin as adding to the goal's pins. Persist the ad-hoc
    # pins (merged with any existing, via effective_pins) so a later re-derive
    # honors them instead of silently dropping the must-haves.
    if pinned:
        goal_svc.update(db, goal_id, GoalUpdate(pinned_method_families=effective_pins))

    return TaxonomyDeriveResult(
        goal_id=goal_id,
        workspace_id=goal.workspace_id,
        dry_run=False,
        chunks_sampled=len(chunks),
        papers_sampled=papers,
        families=families,
        terms_created=terms_created,
        relationships_created=rels_created,
    )
