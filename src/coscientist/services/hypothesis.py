import json
import uuid
from datetime import datetime, timezone
from itertools import combinations
from statistics import median

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.hypothesis import HypothesisCard
from coscientist.models.ontology import OntologyRelationship, OntologyTerm
from coscientist.schemas.approach import ApproachCardResponse, ApproachStatusEnum
from coscientist.schemas.hypothesis import (
    CompatibilityNote,
    HypothesisCardCreate,
    HypothesisCardResponse,
    HypothesisCardUpdate,
    HypothesisGenerateRequest,
    HypothesisGenerateResponse,
    HypothesisStatusEnum,
    HypothesisTypeEnum,
)
from coscientist.schemas.score import ApproachScoreResponse
from coscientist.services import approach as approach_svc
from coscientist.services import goal as goal_svc
from coscientist.services import score as score_svc

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    HypothesisStatusEnum.generated:           {HypothesisStatusEnum.reviewed, HypothesisStatusEnum.superseded},
    HypothesisStatusEnum.reviewed:            {HypothesisStatusEnum.experiment_proposed, HypothesisStatusEnum.superseded},
    HypothesisStatusEnum.experiment_proposed:  {HypothesisStatusEnum.superseded},
    HypothesisStatusEnum.superseded:          set(),
}


def _to_response(card: HypothesisCard) -> HypothesisCardResponse:
    return HypothesisCardResponse(
        id=card.id,
        workspace_id=card.workspace_id,
        name=card.name,
        text=card.text,
        rationale=card.rationale,
        hypothesis_type=HypothesisTypeEnum(card.hypothesis_type),
        approach_ids=json.loads(card.approach_ids) if card.approach_ids else [],
        assumptions=json.loads(card.assumptions) if card.assumptions else [],
        expected_benefits=json.loads(card.expected_benefits) if card.expected_benefits else [],
        failure_modes=json.loads(card.failure_modes) if card.failure_modes else [],
        required_experiments=json.loads(card.required_experiments) if card.required_experiments else [],
        compatibility_notes=[
            CompatibilityNote(**n)
            for n in json.loads(card.compatibility_notes)
        ] if card.compatibility_notes else [],
        has_conflicts=card.has_conflicts,
        status=HypothesisStatusEnum(card.status),
        generation_run_id=card.generation_run_id,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _get_or_404(db: Session, hypothesis_id: str) -> HypothesisCard:
    card = db.get(HypothesisCard, hypothesis_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Hypothesis {hypothesis_id!r} not found")
    return card


def create(db: Session, goal_id: str, data: HypothesisCardCreate) -> HypothesisCardResponse:
    goal = goal_svc.get(db, goal_id)
    for aid in data.approach_ids:
        card = db.get(ApproachCard, aid)
        if card is None:
            raise HTTPException(status_code=404, detail=f"Approach {aid!r} not found")
        if card.workspace_id != goal.workspace_id:
            raise HTTPException(status_code=422, detail=f"Approach {aid!r} belongs to a different workspace")

    now = datetime.now(timezone.utc)
    card = HypothesisCard(
        id=str(uuid.uuid4()),
        workspace_id=goal.workspace_id,
        name=data.name,
        text=data.text,
        rationale=data.rationale,
        hypothesis_type=data.hypothesis_type.value,
        approach_ids=json.dumps(data.approach_ids),
        assumptions=json.dumps(data.assumptions),
        expected_benefits=json.dumps(data.expected_benefits),
        failure_modes=json.dumps(data.failure_modes),
        required_experiments=json.dumps(data.required_experiments),
        compatibility_notes=json.dumps([n.model_dump() for n in data.compatibility_notes]),
        has_conflicts=data.has_conflicts,
        status=HypothesisStatusEnum.generated.value,
        generation_run_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def get(db: Session, hypothesis_id: str) -> HypothesisCardResponse:
    return _to_response(_get_or_404(db, hypothesis_id))


def list_hypotheses(
    db: Session,
    goal_id: str,
    *,
    status: HypothesisStatusEnum | None = None,
    hypothesis_type: HypothesisTypeEnum | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[HypothesisCardResponse], int]:
    goal_svc.get(db, goal_id)
    q = select(HypothesisCard).where(HypothesisCard.workspace_id == goal_id)
    if status is not None:
        q = q.where(HypothesisCard.status == status.value)
    if hypothesis_type is not None:
        q = q.where(HypothesisCard.hypothesis_type == hypothesis_type.value)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(HypothesisCard.name).offset(skip).limit(limit)).all()
    return [_to_response(r) for r in rows], total or 0


def update(db: Session, hypothesis_id: str, data: HypothesisCardUpdate) -> HypothesisCardResponse:
    card = _get_or_404(db, hypothesis_id)
    if data.name is not None:
        card.name = data.name
    if data.text is not None:
        card.text = data.text
    if data.rationale is not None:
        card.rationale = data.rationale
    if data.assumptions is not None:
        card.assumptions = json.dumps(data.assumptions)
    if data.expected_benefits is not None:
        card.expected_benefits = json.dumps(data.expected_benefits)
    if data.failure_modes is not None:
        card.failure_modes = json.dumps(data.failure_modes)
    if data.required_experiments is not None:
        card.required_experiments = json.dumps(data.required_experiments)
    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def transition(db: Session, hypothesis_id: str, new_status: HypothesisStatusEnum) -> HypothesisCardResponse:
    card = _get_or_404(db, hypothesis_id)
    current = HypothesisStatusEnum(card.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        allowed = {s.value for s in ALLOWED_TRANSITIONS[current]}
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition from {current.value!r} to {new_status.value!r}. "
                f"Allowed: {sorted(allowed) or 'none (terminal state)'}"
            ),
        )
    card.status = new_status.value
    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def delete(db: Session, hypothesis_id: str) -> None:
    card = _get_or_404(db, hypothesis_id)
    if card.status != HypothesisStatusEnum.generated.value:
        raise HTTPException(
            status_code=409,
            detail=f"Only generated hypotheses can be deleted; hypothesis is {card.status!r}",
        )
    db.delete(card)
    db.commit()


_HARDWARE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "microphone": ("microphone", "mic array", "error mic", "reference mic"),
    "loudspeaker array": (
        "loudspeaker", "speaker array", "speaker", "desktop bar",
        "soundbar", "sound bar",
    ),
    "dsp": (
        "dsp", "digital signal processing", "digital signal processor",
        "fpga", "gpu", "real-time processor", "adaptive filter",
        "filter computation",
    ),
    "headphone": ("headphone", "earphone"),
    "headrest": ("headrest", "head rest"),
    "parametric loudspeaker": ("parametric loudspeaker", "mcpl"),
}


def _norm(s: str) -> str:
    """Lowercase and collapse underscores/hyphens to spaces for lenient matching."""
    return s.lower().replace("_", " ").replace("-", " ")


def _canonical_hardware(requirements: list[str]) -> set[str]:
    """Map prose hardware requirements onto canonical PSZ hardware concepts.

    Exact set intersection on human-written strings never overlaps; this
    collapses varied prose ("Digital signal processors", "DSP hardware") to a
    shared concept token so genuinely-common hardware registers.
    """
    text = " ".join(_norm(r) for r in requirements)
    return {
        concept
        for concept, keywords in _HARDWARE_CONCEPTS.items()
        if any(kw in text for kw in keywords)
    }


def _find_complementary_dimensions(
    scores_a: ApproachScoreResponse,
    scores_b: ApproachScoreResponse,
    high_threshold: float | None = None,
    low_threshold: float | None = None,
) -> list[str]:
    high = high_threshold if high_threshold is not None else settings.hypothesis_complementary_high
    low = low_threshold if low_threshold is not None else settings.hypothesis_complementary_low
    a_dims = {d.dimension.value: d.score for d in scores_a.dimensions}
    b_dims = {d.dimension.value: d.score for d in scores_b.dimensions}
    complementary = []
    for dim in a_dims:
        a_val = a_dims.get(dim, 0.0)
        b_val = b_dims.get(dim, 0.0)
        if (a_val >= high and b_val <= low) or (b_val >= high and a_val <= low):
            complementary.append(dim)
    return complementary


def _find_assumption_conflicts(assumptions_a: list[str], assumptions_b: list[str]) -> list[str]:
    conflicts = []
    negation_prefixes = ["does not require", "no ", "without "]
    for a in assumptions_a:
        a_lower = a.lower()
        for b in assumptions_b:
            b_lower = b.lower()
            for neg in negation_prefixes:
                if neg in a_lower and a_lower.replace(neg, "").strip() in b_lower:
                    conflicts.append(f"{a} vs {b}")
                elif neg in b_lower and b_lower.replace(neg, "").strip() in a_lower:
                    conflicts.append(f"{a} vs {b}")
    return conflicts


def _check_ontology_related(db: Session, method_a: str, method_b: str) -> bool:
    term_a = db.scalar(
        select(OntologyTerm).where(
            OntologyTerm.category == "method",
            OntologyTerm.canonical_name == method_a,
            OntologyTerm.status == "active",
        )
    )
    term_b = db.scalar(
        select(OntologyTerm).where(
            OntologyTerm.category == "method",
            OntologyTerm.canonical_name == method_b,
            OntologyTerm.status == "active",
        )
    )
    if not term_a or not term_b:
        return False

    rel = db.scalar(
        select(OntologyRelationship).where(
            or_(
                (OntologyRelationship.source_term_id == term_a.id)
                & (OntologyRelationship.target_term_id == term_b.id),
                (OntologyRelationship.source_term_id == term_b.id)
                & (OntologyRelationship.target_term_id == term_a.id),
            )
        )
    )
    return rel is not None


def _check_compatibility(
    approach_a: ApproachCardResponse,
    approach_b: ApproachCardResponse,
    scores_a: ApproachScoreResponse | None,
    scores_b: ApproachScoreResponse | None,
    db: Session,
) -> CompatibilityNote:
    hw_a = _canonical_hardware(approach_a.hardware_requirements)
    hw_b = _canonical_hardware(approach_b.hardware_requirements)
    shared_hw = sorted(hw_a & hw_b)

    conflicts = _find_assumption_conflicts(
        approach_a.key_assumptions, approach_b.key_assumptions,
    )

    complementary = []
    if scores_a and scores_b:
        complementary = _find_complementary_dimensions(scores_a, scores_b)

    ontology_related = _check_ontology_related(db, approach_a.method_family, approach_b.method_family)

    compatible = len(conflicts) == 0

    note_parts = []
    if shared_hw:
        note_parts.append(f"Shared hardware: {', '.join(shared_hw)}")
    if ontology_related:
        note_parts.append(f"{approach_a.method_family} and {approach_b.method_family} are related in the ontology")
    if complementary:
        note_parts.append(f"Complementary on: {', '.join(complementary)}")
    if conflicts:
        note_parts.append(f"Assumption conflicts: {'; '.join(conflicts)}")

    return CompatibilityNote(
        approach_a_id=approach_a.id,
        approach_b_id=approach_b.id,
        compatible=compatible,
        shared_hardware=shared_hw,
        conflicting_assumptions=conflicts,
        complementary_dimensions=complementary,
        ontology_related=ontology_related,
        note=". ".join(note_parts) if note_parts else "No significant compatibility signals found",
    )


def _synthesize_hypothesis(
    approaches: list[ApproachCardResponse],
    scores_list: list[ApproachScoreResponse | None],
    compatibility: list[CompatibilityNote],
    hypothesis_type: HypothesisTypeEnum,
    generation_run_id: str,
    workspace_id: str,
    now: datetime,
) -> HypothesisCard:
    method_names = [a.method_family.replace("_", " ").title() for a in approaches]
    name = " + ".join(method_names)

    all_complementary = set()
    all_shared_hw = set()
    ontology_related = False
    has_conflicts = False
    conflict_details = []
    for cn in compatibility:
        all_complementary.update(cn.complementary_dimensions)
        all_shared_hw.update(cn.shared_hardware)
        if cn.ontology_related:
            ontology_related = True
        if not cn.compatible:
            has_conflicts = True
            conflict_details.extend(cn.conflicting_assumptions)

    text_parts = [f"Combine {' and '.join(method_names)}"]
    if all_complementary:
        text_parts.append(f"to leverage complementary strengths in {', '.join(sorted(all_complementary))}")
    text = " ".join(text_parts) + "."

    rationale_parts = []
    if all_complementary:
        rationale_parts.append(
            f"Approaches are complementary on {len(all_complementary)} dimensions: "
            f"{', '.join(sorted(all_complementary))}"
        )
    if all_shared_hw:
        rationale_parts.append(f"Share hardware: {', '.join(sorted(all_shared_hw))}")
    if ontology_related:
        method_names_lower = ", ".join(a.method_family.replace("_", " ") for a in approaches)
        rationale_parts.append(f"Methods are related in the ontology ({method_names_lower})")
    if has_conflicts:
        rationale_parts.append(f"WARNING: {len(conflict_details)} assumption conflicts detected")
    if not rationale_parts:
        rationale_parts.append("Methods may be combined for broader coverage")
    rationale = ". ".join(rationale_parts) + "."

    all_assumptions = list(dict.fromkeys(
        a for approach in approaches for a in approach.key_assumptions
    ))

    expected_benefits = sorted(all_complementary) if all_complementary else [
        f"Broader coverage of {a.method_family}" for a in approaches
    ]

    all_failure_modes = list(dict.fromkeys(
        fm
        for approach in approaches
        for r in approach.risks_and_limitations
        if r.failure_mode
        for fm in [r.failure_mode]
    ))

    all_experiments = list(dict.fromkeys(
        e
        for approach in approaches
        for e in approach.suggested_experiments
    ))
    all_experiments.append(f"Validate combined {' + '.join(a.method_family for a in approaches)} approach")

    return HypothesisCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=name,
        text=text,
        rationale=rationale,
        hypothesis_type=hypothesis_type.value,
        approach_ids=json.dumps([a.id for a in approaches]),
        assumptions=json.dumps(all_assumptions),
        expected_benefits=json.dumps(expected_benefits),
        failure_modes=json.dumps(all_failure_modes),
        required_experiments=json.dumps(all_experiments),
        compatibility_notes=json.dumps([cn.model_dump() for cn in compatibility]),
        has_conflicts=has_conflicts,
        status=HypothesisStatusEnum.generated.value,
        generation_run_id=generation_run_id,
        created_at=now,
        updated_at=now,
    )


def _get_existing_approach_sets(db: Session, workspace_id: str) -> set[frozenset[str]]:
    existing = db.scalars(
        select(HypothesisCard).where(
            HypothesisCard.workspace_id == workspace_id,
            HypothesisCard.status != HypothesisStatusEnum.superseded.value,
        )
    ).all()
    return {
        frozenset(json.loads(h.approach_ids))
        for h in existing
    }


def generate_hypotheses(
    db: Session,
    goal_id: str,
    request: HypothesisGenerateRequest,
) -> HypothesisGenerateResponse:
    goal = goal_svc.get(db, goal_id)

    approaches_raw = db.scalars(
        select(ApproachCard).where(
            ApproachCard.workspace_id == goal_id,
            ApproachCard.status.in_([
                ApproachStatusEnum.scored.value,
                ApproachStatusEnum.experiment_proposed.value,
            ]),
        )
    ).all()

    approaches: list[ApproachCardResponse] = [
        approach_svc.get(db, a.id) for a in approaches_raw
    ]

    if len(approaches) < request.min_approaches:
        return HypothesisGenerateResponse(
            generation_run_id=str(uuid.uuid4()),
            goal_id=goal_id,
            hypotheses_created=0,
            hypotheses_skipped_duplicate=0,
            conservative_count=0,
            exploratory_count=0,
            hypotheses=[],
        )

    scores_map: dict[str, ApproachScoreResponse | None] = {}
    for a in approaches:
        try:
            scores_map[a.id] = score_svc.get_scores(db, a.id)
        except HTTPException:
            scores_map[a.id] = None

    final_scores = [
        s.final_score for s in scores_map.values() if s is not None
    ]
    med = median(final_scores) if final_scores else 0.0

    compat_cache: dict[frozenset[str], CompatibilityNote] = {}
    for a, b in combinations(approaches, 2):
        key = frozenset([a.id, b.id])
        compat_cache[key] = _check_compatibility(a, b, scores_map[a.id], scores_map[b.id], db)

    existing_sets = _get_existing_approach_sets(db, goal_id)
    generation_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created: list[HypothesisCard] = []
    skipped = 0
    conservative_count = 0
    exploratory_count = 0

    for a, b in combinations(approaches, 2):
        if len(created) >= request.max_hypotheses:
            break

        pair_key = frozenset([a.id, b.id])
        if pair_key in existing_sets:
            skipped += 1
            continue

        cn = compat_cache[pair_key]
        sa = scores_map.get(a.id)
        sb = scores_map.get(b.id)

        a_above = sa is not None and sa.final_score >= med
        b_above = sb is not None and sb.final_score >= med

        is_conservative = (
            a_above and b_above
            and cn.compatible
            and (len(cn.complementary_dimensions) > 0 or cn.note != "No significant compatibility signals found")
        )

        is_exploratory = (
            not is_conservative
            and (a_above or b_above)
            and (len(cn.complementary_dimensions) > 0 or not cn.compatible)
        )

        if is_conservative:
            card = _synthesize_hypothesis(
                [a, b], [sa, sb], [cn],
                HypothesisTypeEnum.conservative,
                generation_run_id, goal_id, now,
            )
            db.add(card)
            created.append(card)
            conservative_count += 1
        elif is_exploratory and request.include_exploratory:
            card = _synthesize_hypothesis(
                [a, b], [sa, sb], [cn],
                HypothesisTypeEnum.exploratory,
                generation_run_id, goal_id, now,
            )
            db.add(card)
            created.append(card)
            exploratory_count += 1

    db.commit()
    for card in created:
        db.refresh(card)

    return HypothesisGenerateResponse(
        generation_run_id=generation_run_id,
        goal_id=goal_id,
        hypotheses_created=len(created),
        hypotheses_skipped_duplicate=skipped,
        conservative_count=conservative_count,
        exploratory_count=exploratory_count,
        hypotheses=[_to_response(c) for c in created],
    )
