import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from coscientist.models.approach import ApproachCard
from coscientist.models.evidence import EvidenceRecord
from coscientist.models.ontology import OntologyRelationship, OntologyTerm
from coscientist.models.score import RubricScore
from coscientist.schemas.approach import (
    ApproachCardResponse,
    ApproachStatusEnum,
    ReportedMetric,
    RiskItem,
)
from coscientist.schemas.score import (
    ApproachScoreResponse,
    DimensionRanking,
    DimensionScoreResponse,
    ParetoResponse,
    RubricDimensionEnum,
    ScoreComparisonResponse,
    WeightProfileEnum,
)
from coscientist.services import approach as approach_svc
from coscientist.services import goal as goal_svc

WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "default": {
        "evidence_strength": 0.15,
        "reproducibility": 0.12,
        "acoustic_performance": 0.15,
        "robustness": 0.12,
        "realtime_feasibility": 0.10,
        "hardware_feasibility": 0.10,
        "calibration_burden": 0.08,
        "composability": 0.08,
        "measurement_clarity": 0.05,
        "device_relevance": 0.05,
    },
    "fastest_prototype": {
        "evidence_strength": 0.08,
        "reproducibility": 0.08,
        "acoustic_performance": 0.10,
        "robustness": 0.08,
        "realtime_feasibility": 0.18,
        "hardware_feasibility": 0.18,
        "calibration_burden": 0.14,
        "composability": 0.04,
        "measurement_clarity": 0.04,
        "device_relevance": 0.08,
    },
    "scientific_novelty": {
        "evidence_strength": 0.22,
        "reproducibility": 0.18,
        "acoustic_performance": 0.15,
        "robustness": 0.08,
        "realtime_feasibility": 0.05,
        "hardware_feasibility": 0.05,
        "calibration_burden": 0.05,
        "composability": 0.07,
        "measurement_clarity": 0.10,
        "device_relevance": 0.05,
    },
    "robustness": {
        "evidence_strength": 0.12,
        "reproducibility": 0.10,
        "acoustic_performance": 0.12,
        "robustness": 0.22,
        "realtime_feasibility": 0.10,
        "hardware_feasibility": 0.08,
        "calibration_burden": 0.12,
        "composability": 0.06,
        "measurement_clarity": 0.05,
        "device_relevance": 0.03,
    },
    "product_feasibility": {
        "evidence_strength": 0.08,
        "reproducibility": 0.08,
        "acoustic_performance": 0.12,
        "robustness": 0.10,
        "realtime_feasibility": 0.16,
        "hardware_feasibility": 0.16,
        "calibration_burden": 0.08,
        "composability": 0.04,
        "measurement_clarity": 0.04,
        "device_relevance": 0.14,
    },
}

_ACOUSTIC_KEYWORDS = {
    "acoustic_contrast", "sound_pressure", "bright_zone", "dark_zone",
    "acoustic_contrast_db", "sound_field", "isolation", "separation",
    "spl", "acoustic_energy", "acoustic_goal",
}

_REALTIME_KEYWORDS = {"latency", "latency_ms", "real_time", "realtime", "compute", "processing_time"}

_CALIBRATION_KEYWORDS = {"calibration", "calibrate", "setup", "initialization", "adaptation"}


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _norm(s: str) -> str:
    """Lowercase and collapse underscores/hyphens to spaces for lenient matching."""
    return s.lower().replace("_", " ").replace("-", " ")


def _get_evidence_for_approach(db: Session, approach: ApproachCardResponse) -> list[EvidenceRecord]:
    evidence_ids = [el.evidence_id for el in approach.evidence_links]
    if not evidence_ids:
        return []
    return list(db.scalars(
        select(EvidenceRecord).where(EvidenceRecord.id.in_(evidence_ids))
    ).all())


def _score_evidence_strength(
    approach: ApproachCardResponse, evidence: list[EvidenceRecord],
) -> tuple[float, float | None, str, list[str], bool]:
    if not evidence:
        return 0.0, 0.0, "No evidence records linked", [], True

    strong = sum(1 for e in evidence if e.evidence_strength == "strong")
    total = len(evidence)
    paper_ids = {e.paper_id for e in evidence}
    score = _clamp(strong / total if total > 0 else 0.0)
    paper_bonus = _clamp(len(paper_ids) / 10.0)
    score = _clamp(score * 0.7 + paper_bonus * 0.3)
    confidence = _clamp(total / 10.0)
    low = total < 3
    rationale = (
        f"{strong}/{total} evidence records classified as strong, "
        f"across {len(paper_ids)} papers"
    )
    return score, confidence, rationale, [e.id for e in evidence], low


def _score_reproducibility(
    approach: ApproachCardResponse,
) -> tuple[float, float | None, str, list[str], bool]:
    maturity_map = {"theoretical": 0.2, "simulated": 0.5, "measured": 0.8, "validated": 1.0}
    mat_score = maturity_map.get(approach.maturity.value, 0.1)
    metrics_with_values = [m for m in approach.reported_metrics if m.value is not None]
    metric_score = _clamp(len(metrics_with_values) / 5.0)
    score = _clamp(mat_score * 0.6 + metric_score * 0.4)
    low = approach.maturity.value == "theoretical" and len(metrics_with_values) == 0
    rationale = (
        f"Maturity: {approach.maturity.value} ({mat_score:.1f}), "
        f"{len(metrics_with_values)} metrics with explicit values"
    )
    return score, None, rationale, [], low


def _score_acoustic_performance(
    approach: ApproachCardResponse, evidence: list[EvidenceRecord],
) -> tuple[float, float | None, str, list[str], bool]:
    acoustic_kw = [_norm(kw) for kw in _ACOUSTIC_KEYWORDS]
    acoustic_evidence = []
    for e in evidence:
        metrics = json.loads(e.metric_names) if e.metric_names else []
        if any(any(kw in _norm(m) for kw in acoustic_kw) for m in metrics):
            acoustic_evidence.append(e)

    metric_coverage = sum(
        1 for m in approach.reported_metrics
        if any(kw in _norm(m.metric_name) for kw in acoustic_kw)
    )
    ev_score = _clamp(len(acoustic_evidence) / 5.0)
    met_score = _clamp(metric_coverage / 3.0)
    score = _clamp(ev_score * 0.6 + met_score * 0.4)
    low = len(acoustic_evidence) == 0 and metric_coverage == 0
    rationale = (
        f"{len(acoustic_evidence)} acoustic evidence records, "
        f"{metric_coverage} acoustic metrics reported"
    )
    return score, None, rationale, [e.id for e in acoustic_evidence], low


def _score_robustness(
    approach: ApproachCardResponse,
) -> tuple[float, float | None, str, list[str], bool]:
    risk_count = len(approach.risks_and_limitations)
    failure_modes = [r for r in approach.risks_and_limitations if r.failure_mode]
    if risk_count == 0:
        score = 0.3
        low = True
        rationale = "No failure modes documented — robustness unknown"
    else:
        coverage = _clamp(len(failure_modes) / 5.0)
        score = _clamp(0.4 + coverage * 0.6)
        low = False
        rationale = (
            f"{len(failure_modes)} failure modes identified out of "
            f"{risk_count} total risks"
        )
    eids = [r.evidence_id for r in approach.risks_and_limitations if r.evidence_id]
    return score, None, rationale, eids, low


def _score_realtime_feasibility(
    approach: ApproachCardResponse,
) -> tuple[float, float | None, str, list[str], bool]:
    rt_metrics = [
        m for m in approach.reported_metrics
        if any(kw in m.metric_name.lower() for kw in _REALTIME_KEYWORDS)
    ]
    if rt_metrics:
        score = _clamp(0.5 + len(rt_metrics) * 0.25)
        low = False
        rationale = f"{len(rt_metrics)} realtime-related metrics reported"
    else:
        text = (approach.mechanism_summary or "").lower()
        has_mention = any(kw in text for kw in _REALTIME_KEYWORDS)
        score = 0.4 if has_mention else 0.2
        low = not has_mention
        rationale = (
            "Realtime mentioned in mechanism summary" if has_mention
            else "No realtime/latency information found"
        )
    eids = [m.source_evidence_id for m in rt_metrics if m.source_evidence_id]
    return score, None, rationale, eids, low


def _score_hardware_feasibility(
    approach: ApproachCardResponse, goal_response,
) -> tuple[float, float | None, str, list[str], bool]:
    hw = approach.hardware_requirements
    if not hw:
        score = 0.5
        return score, None, "No hardware requirements specified", [], True

    dc = goal_response.device_constraints
    if not dc:
        score = _clamp(1.0 - len(hw) * 0.15)
        return score, None, f"{len(hw)} hardware requirements, no goal constraints to match", [], False

    matches = 0
    total_checks = 0
    if dc.form_factor:
        total_checks += 1
        if any(_norm(dc.form_factor) in _norm(h) for h in hw):
            matches += 1
    if dc.speaker_count:
        total_checks += 1
        if any("speaker" in h.lower() or "loudspeaker" in h.lower() for h in hw):
            matches += 1

    if total_checks > 0:
        score = _clamp(matches / total_checks)
    else:
        score = 0.5

    rationale = (
        f"{len(hw)} hardware requirements, "
        f"{matches}/{total_checks} match goal constraints"
    )
    return score, None, rationale, [], False


def _score_calibration_burden(
    approach: ApproachCardResponse, evidence: list[EvidenceRecord],
) -> tuple[float, float | None, str, list[str], bool]:
    cal_metrics = [
        m for m in approach.reported_metrics
        if any(kw in m.metric_name.lower() for kw in _CALIBRATION_KEYWORDS)
    ]
    cal_evidence = []
    for e in evidence:
        text = (e.chunk_text or "").lower()
        if any(kw in text for kw in _CALIBRATION_KEYWORDS):
            cal_evidence.append(e)

    if cal_metrics or cal_evidence:
        score = _clamp(0.5 + len(cal_metrics) * 0.2 + len(cal_evidence) * 0.1)
        low = False
        rationale = (
            f"{len(cal_metrics)} calibration metrics, "
            f"{len(cal_evidence)} calibration-related evidence chunks"
        )
    else:
        score = 0.3
        low = True
        rationale = "No calibration information found"
    return score, None, rationale, [e.id for e in cal_evidence], low


def _score_composability(
    approach: ApproachCardResponse, db: Session,
) -> tuple[float, float | None, str, list[str], bool]:
    method_term = db.scalar(
        select(OntologyTerm).where(
            OntologyTerm.category == "method",
            OntologyTerm.canonical_name == approach.method_family,
            OntologyTerm.status == "active",
        )
    )
    if not method_term:
        return 0.3, None, f"No ontology term found for {approach.method_family}", [], True

    from sqlalchemy import or_
    rels = db.scalars(
        select(OntologyRelationship).where(
            or_(
                OntologyRelationship.source_term_id == method_term.id,
                OntologyRelationship.target_term_id == method_term.id,
            )
        )
    ).all()

    related_count = len(rels)
    score = _clamp(related_count / 5.0)
    rationale = f"{related_count} related methods in ontology for {approach.method_family}"
    return score, None, rationale, [], related_count == 0


def _score_measurement_clarity(
    approach: ApproachCardResponse,
) -> tuple[float, float | None, str, list[str], bool]:
    total = len(approach.reported_metrics)
    with_values = [m for m in approach.reported_metrics if m.value is not None]
    with_units = [m for m in with_values if m.unit is not None]

    if total == 0:
        return 0.1, None, "No reported metrics", [], True

    value_ratio = len(with_values) / total
    unit_ratio = len(with_units) / total if total > 0 else 0.0
    score = _clamp(value_ratio * 0.6 + unit_ratio * 0.4)
    rationale = (
        f"{len(with_values)}/{total} metrics have values, "
        f"{len(with_units)}/{total} have units"
    )
    eids = [m.source_evidence_id for m in with_values if m.source_evidence_id]
    return score, None, rationale, eids, len(with_values) == 0


def _score_device_relevance(
    approach: ApproachCardResponse, goal_response,
) -> tuple[float, float | None, str, list[str], bool]:
    dc = goal_response.device_constraints
    if not dc:
        return 0.5, None, "No device constraints on goal", [], True

    hw = approach.hardware_requirements
    device_text = approach.device_relevance or ""
    matches = 0
    checks = 0

    if dc.form_factor:
        checks += 1
        if _norm(dc.form_factor) in _norm(device_text) or any(
            _norm(dc.form_factor) in _norm(h) for h in hw
        ):
            matches += 1
    if dc.compute_budget:
        checks += 1
        if _norm(dc.compute_budget) in _norm(device_text) or any(
            _norm(dc.compute_budget) in _norm(h) for h in hw
        ):
            matches += 1

    if checks == 0:
        return 0.5, None, "No device constraint fields to match", [], True

    score = _clamp(matches / checks)
    rationale = f"{matches}/{checks} device constraint fields matched"
    return score, None, rationale, [], matches == 0


_DIMENSION_SCORERS = {
    "evidence_strength": lambda a, e, g, db: _score_evidence_strength(a, e),
    "reproducibility": lambda a, e, g, db: _score_reproducibility(a),
    "acoustic_performance": lambda a, e, g, db: _score_acoustic_performance(a, e),
    "robustness": lambda a, e, g, db: _score_robustness(a),
    "realtime_feasibility": lambda a, e, g, db: _score_realtime_feasibility(a),
    "hardware_feasibility": lambda a, e, g, db: _score_hardware_feasibility(a, g),
    "calibration_burden": lambda a, e, g, db: _score_calibration_burden(a, e),
    "composability": lambda a, e, g, db: _score_composability(a, db),
    "measurement_clarity": lambda a, e, g, db: _score_measurement_clarity(a),
    "device_relevance": lambda a, e, g, db: _score_device_relevance(a, g),
}


def _compute_risk_penalty(approach: ApproachCardResponse) -> float:
    # A card that discloses no risks at all is unassessed, not risk-free —
    # penalize it at the cap so omission never beats honest disclosure.
    if not approach.risks_and_limitations:
        return 0.2
    high_risks = sum(
        1 for r in approach.risks_and_limitations
        if r.severity and r.severity.lower() == "high"
    )
    return min(high_risks * 0.05, 0.2)


def _get_approach_or_404(db: Session, approach_id: str) -> ApproachCard:
    card = db.get(ApproachCard, approach_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Approach {approach_id!r} not found")
    return card


def score_approach(
    db: Session,
    approach_id: str,
    weight_profile: WeightProfileEnum = WeightProfileEnum.default,
) -> ApproachScoreResponse:
    approach = approach_svc.get(db, approach_id)
    card = _get_approach_or_404(db, approach_id)
    goal = goal_svc.get(db, approach.workspace_id)
    evidence = _get_evidence_for_approach(db, approach)
    weights = WEIGHT_PROFILES[weight_profile.value]
    scoring_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db.execute(
        delete(RubricScore).where(RubricScore.approach_id == approach_id)
    )

    dimensions: list[DimensionScoreResponse] = []
    total_score = 0.0

    for dim_name in RubricDimensionEnum:
        scorer = _DIMENSION_SCORERS[dim_name.value]
        score_val, confidence, rationale, eids, low_conf = scorer(approach, evidence, goal, db)
        weight = weights[dim_name.value]
        weighted = score_val * weight

        row = RubricScore(
            id=str(uuid.uuid4()),
            approach_id=approach_id,
            workspace_id=approach.workspace_id,
            dimension=dim_name.value,
            score=score_val,
            weight=weight,
            weighted_score=weighted,
            confidence=confidence,
            rationale=rationale,
            evidence_ids=json.dumps(eids),
            low_confidence=low_conf,
            scoring_run_id=scoring_run_id,
            created_at=now,
        )
        db.add(row)
        total_score += weighted

        dimensions.append(DimensionScoreResponse(
            dimension=dim_name,
            score=score_val,
            weight=weight,
            weighted_score=weighted,
            confidence=confidence,
            rationale=rationale,
            evidence_ids=eids,
            low_confidence=low_conf,
        ))

    risk_penalty = _compute_risk_penalty(approach)
    final_score = max(0.0, total_score - risk_penalty)

    if card.status == ApproachStatusEnum.reviewed.value:
        card.status = ApproachStatusEnum.scored.value
        card.updated_at = now

    db.commit()

    return ApproachScoreResponse(
        approach_id=approach_id,
        approach_name=approach.name,
        method_family=approach.method_family,
        dimensions=dimensions,
        total_score=round(total_score, 4),
        risk_penalty=round(risk_penalty, 4),
        final_score=round(final_score, 4),
        scoring_run_id=scoring_run_id,
    )


def score_all_approaches(
    db: Session,
    goal_id: str,
    weight_profile: WeightProfileEnum = WeightProfileEnum.default,
) -> list[ApproachScoreResponse]:
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ApproachCard).where(
            ApproachCard.workspace_id == goal_id,
            ApproachCard.status.in_([
                ApproachStatusEnum.reviewed.value,
                ApproachStatusEnum.scored.value,
            ]),
        )
    ).all()

    results = []
    for card in cards:
        result = score_approach(db, card.id, weight_profile)
        results.append(result)

    return results


def get_scores(db: Session, approach_id: str) -> ApproachScoreResponse:
    approach = approach_svc.get(db, approach_id)
    rows = list(db.scalars(
        select(RubricScore)
        .where(RubricScore.approach_id == approach_id)
        .order_by(RubricScore.dimension)
    ).all())

    if not rows:
        raise HTTPException(status_code=404, detail=f"No scores found for approach {approach_id!r}")

    dimensions = []
    total_score = 0.0
    scoring_run_id = rows[0].scoring_run_id

    for row in rows:
        dimensions.append(DimensionScoreResponse(
            dimension=RubricDimensionEnum(row.dimension),
            score=row.score,
            weight=row.weight,
            weighted_score=row.weighted_score,
            confidence=row.confidence,
            rationale=row.rationale,
            evidence_ids=json.loads(row.evidence_ids),
            low_confidence=row.low_confidence,
        ))
        total_score += row.weighted_score

    risk_penalty = _compute_risk_penalty(approach)
    final_score = max(0.0, total_score - risk_penalty)

    return ApproachScoreResponse(
        approach_id=approach_id,
        approach_name=approach.name,
        method_family=approach.method_family,
        dimensions=dimensions,
        total_score=round(total_score, 4),
        risk_penalty=round(risk_penalty, 4),
        final_score=round(final_score, 4),
        scoring_run_id=scoring_run_id,
    )


def _build_dimension_rankings(
    scored: list[ApproachScoreResponse],
) -> list[DimensionRanking]:
    rankings = []
    for dim in RubricDimensionEnum:
        dim_scores = []
        for s in scored:
            for d in s.dimensions:
                if d.dimension == dim:
                    dim_scores.append({
                        "approach_id": s.approach_id,
                        "approach_name": s.approach_name,
                        "score": d.score,
                        "weighted_score": d.weighted_score,
                    })
                    break
        dim_scores.sort(key=lambda x: x["score"], reverse=True)
        for rank, entry in enumerate(dim_scores, 1):
            entry["rank"] = rank
        rankings.append(DimensionRanking(dimension=dim, rankings=dim_scores))
    return rankings


def get_comparison(
    db: Session,
    goal_id: str,
    weight_profile: WeightProfileEnum = WeightProfileEnum.default,
) -> ScoreComparisonResponse:
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ApproachCard).where(
            ApproachCard.workspace_id == goal_id,
            ApproachCard.status.in_([
                ApproachStatusEnum.scored.value,
                ApproachStatusEnum.reviewed.value,
            ]),
        )
    ).all()

    scored: list[ApproachScoreResponse] = []
    for card in cards:
        try:
            s = get_scores(db, card.id)
            scored.append(s)
        except HTTPException:
            pass

    scored.sort(key=lambda s: s.final_score, reverse=True)
    rankings = _build_dimension_rankings(scored)

    return ScoreComparisonResponse(
        approaches=scored,
        dimension_rankings=rankings,
    )


def _is_dominated(a: ApproachScoreResponse, b: ApproachScoreResponse) -> bool:
    a_dims = {d.dimension: d.score for d in a.dimensions}
    b_dims = {d.dimension: d.score for d in b.dimensions}
    all_dims = set(a_dims) | set(b_dims)
    at_least_one_worse = False
    for dim in all_dims:
        a_val = a_dims.get(dim, 0.0)
        b_val = b_dims.get(dim, 0.0)
        if a_val > b_val:
            return False
        if a_val < b_val:
            at_least_one_worse = True
    return at_least_one_worse


def get_pareto(db: Session, goal_id: str) -> ParetoResponse:
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ApproachCard).where(
            ApproachCard.workspace_id == goal_id,
            ApproachCard.status.in_([
                ApproachStatusEnum.scored.value,
                ApproachStatusEnum.reviewed.value,
            ]),
        )
    ).all()

    scored: list[ApproachScoreResponse] = []
    for card in cards:
        try:
            s = get_scores(db, card.id)
            scored.append(s)
        except HTTPException:
            pass

    pareto: list[ApproachScoreResponse] = []
    dominated: list[ApproachScoreResponse] = []

    for candidate in scored:
        is_dom = any(_is_dominated(candidate, other) for other in scored if other is not candidate)
        if is_dom:
            dominated.append(candidate)
        else:
            pareto.append(candidate)

    rankings = _build_dimension_rankings(scored)

    return ParetoResponse(
        pareto_optimal=pareto,
        dominated=dominated,
        dimension_rankings=rankings,
    )


def rescore(
    db: Session,
    approach_id: str,
    weight_profile: WeightProfileEnum = WeightProfileEnum.default,
) -> ApproachScoreResponse:
    return score_approach(db, approach_id, weight_profile)
