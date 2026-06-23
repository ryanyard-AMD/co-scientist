import json
import uuid
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.device import DeviceConceptCard
from coscientist.models.experiment import ExperimentCard
from coscientist.models.score import RubricScore
from coscientist.models.validation import ValidationResult
from coscientist.schemas.device import (
    AgentDeviceConceptItem,
    AcousticArchitecture,
    DeviceConceptCardListResponse,
    DeviceConceptCardResponse,
    DeviceConceptComparisonItem,
    DeviceConceptComparisonResponse,
    DeviceConceptExportResponse,
    DeviceConceptGenerateRequest,
    DeviceConceptGenerateResponse,
    DeviceConceptStatusEnum,
    ExpectedPerformance,
    FormFactor,
    HardwareSpec,
    UseCase,
)
from coscientist.services import goal as goal_svc

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    DeviceConceptStatusEnum.generated: {
        DeviceConceptStatusEnum.reviewed,
        DeviceConceptStatusEnum.superseded,
    },
    DeviceConceptStatusEnum.reviewed: {DeviceConceptStatusEnum.superseded},
    DeviceConceptStatusEnum.superseded: set(),
}


def _to_response(card: DeviceConceptCard) -> DeviceConceptCardResponse:
    ff_raw = json.loads(card.form_factor) if card.form_factor else {}
    uc_raw = json.loads(card.use_case) if card.use_case else {}
    aa_raw = json.loads(card.acoustic_architecture) if card.acoustic_architecture else {}
    hw_raw = json.loads(card.hardware) if card.hardware else {}
    ep_raw = json.loads(card.expected_performance) if card.expected_performance else {}

    return DeviceConceptCardResponse(
        id=card.id,
        workspace_id=card.workspace_id,
        name=card.name,
        description=card.description,
        status=DeviceConceptStatusEnum(card.status),
        maturity=card.maturity,
        form_factor=FormFactor(**ff_raw),
        use_case=UseCase(**uc_raw),
        acoustic_architecture=AcousticArchitecture(**aa_raw),
        hardware=HardwareSpec(**hw_raw),
        expected_performance=ExpectedPerformance(**ep_raw),
        approach_ids=json.loads(card.approach_ids) if card.approach_ids else [],
        experiment_ids=json.loads(card.experiment_ids) if card.experiment_ids else [],
        validation_result_ids=json.loads(card.validation_result_ids) if card.validation_result_ids else [],
        unresolved_risks=json.loads(card.unresolved_risks) if card.unresolved_risks else [],
        next_steps=json.loads(card.next_steps) if card.next_steps else [],
        rationale=card.rationale,
        model_used=card.model_used,
        generation_run_id=card.generation_run_id,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _get_or_404(db: Session, device_id: str, goal_id: str) -> DeviceConceptCard:
    card = db.get(DeviceConceptCard, device_id)
    if card is None or card.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Device concept {device_id!r} not found")
    return card


def _build_approach_context(
    approach: ApproachCard,
    scores: list[RubricScore],
    experiments: list[ExperimentCard],
    validation_results: list[ValidationResult],
) -> dict:
    approach_scores = [s for s in scores if s.approach_id == approach.id]
    approach_exp_ids = json.loads(approach.approach_ids) if False else []  # placeholder
    approach_exps = [
        e for e in experiments
        if approach.id in json.loads(e.approach_ids or "[]")
    ]
    approach_val_results = [
        v for v in validation_results if v.approach_id == approach.id
    ]

    score_summary = {s.dimension: round(s.weighted_score, 3) for s in approach_scores}

    return {
        "id": approach.id,
        "name": approach.name,
        "method_family": approach.method_family,
        "maturity": approach.maturity,
        "hardware_requirements": json.loads(approach.hardware_requirements or "[]"),
        "risks_and_limitations": json.loads(approach.risks_and_limitations or "[]"),
        "device_relevance": approach.device_relevance or "",
        "rubric_scores": score_summary,
        "experiments": [
            {
                "id": e.id,
                "name": e.name,
                "type": e.experiment_type,
                "status": e.status,
            }
            for e in approach_exps
        ],
        "validation_results": [
            {
                "decision": v.decision,
                "confidence": v.confidence,
                "reasoning": v.reasoning[:200],
            }
            for v in approach_val_results
        ],
    }


def _run_device_agent(
    goal,
    approaches_context: list[dict],
) -> list[AgentDeviceConceptItem]:
    if not approaches_context:
        return []

    success_criteria = json.loads(goal.success_criteria) if isinstance(goal.success_criteria, str) else []
    device_constraints = json.loads(goal.device_constraints) if isinstance(goal.device_constraints, str) else {}

    system_prompt = (
        "You are a Device Integrator Agent for personal sound zone (PSZ) research. "
        "Given validated research approach cards, you synthesise candidate device architectures. "
        "Respond with ONLY a JSON array of device concept objects. No markdown, no explanation.\n\n"
        "Each object must have these exact keys:\n"
        '  "name": string — short descriptive name for the device concept\n'
        '  "description": string — 1-2 sentence overview\n'
        '  "rationale": string — why these approaches combine into this device\n'
        '  "maturity": one of: "theoretical", "simulated", "measured", "validated"\n'
        '  "form_factor": {"type": str, "placement": str, "listener_distance_cm": str}\n'
        '  "use_case": {"primary": str, "secondary": [str, ...]}\n'
        '  "acoustic_architecture": {"control_stack": [str, ...], "calibration": [str, ...], "simulation_backing": [str, ...]}\n'
        '  "hardware": {"speakers": {"estimated_count": int, "geometry": str}, "microphones": {"calibration_count": str, "runtime_feedback": str}, "compute": {"prototype": str, "production_candidate": str}}\n'
        '  "expected_performance": {"bright_zone": str, "dark_zone": str, "latency": str, "robustness": str}\n'
        '  "unresolved_risks": [str, ...] — list of open technical risks\n'
        '  "next_steps": [str, ...] — list of recommended next experiments or prototyping steps\n\n'
        "Propose one device concept per distinct form factor you identify as viable. "
        "Maturity is determined by the weakest validated approach: if any approach is theoretical, the device is theoretical."
    )

    approaches_text = json.dumps(approaches_context, indent=2)
    user_message = (
        f"## Goal\n"
        f"Name: {goal.name}\n"
        f"Description: {goal.description or ''}\n"
        f"Target application: {goal.target_application}\n\n"
        f"## Success Criteria\n{json.dumps(success_criteria, indent=2)}\n\n"
        f"## Device Constraints\n{json.dumps(device_constraints, indent=2)}\n\n"
        f"## Validated Research Approaches\n{approaches_text}\n\n"
        "Synthesise candidate device architectures from these approaches. "
        "Group compatible approaches into coherent device concepts. "
        "Consider form factor compatibility, hardware overlap, and combined control stacks."
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.validation_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            data = [data]
        return [AgentDeviceConceptItem(**item) for item in data]
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Device agent returned unparseable response: {exc}",
        )


def generate(
    db: Session,
    goal_id: str,
    request: DeviceConceptGenerateRequest,
) -> DeviceConceptGenerateResponse:
    goal = goal_svc.get(db, goal_id)  # raises 404 if not found

    # Load approaches: validated first, then scored if explicitly requested
    stmt = select(ApproachCard).where(ApproachCard.workspace_id == goal_id)
    if request.approach_ids:
        stmt = stmt.where(ApproachCard.id.in_(request.approach_ids))
    else:
        stmt = stmt.where(ApproachCard.status.in_(["validated", "scored"]))
    approaches = list(db.scalars(stmt))

    if not approaches:
        return DeviceConceptGenerateResponse(
            generated=0,
            generation_run_id=str(uuid.uuid4()),
            items=[],
        )

    approach_ids = [a.id for a in approaches]

    # Load rubric scores
    scores = list(
        db.scalars(
            select(RubricScore).where(RubricScore.approach_id.in_(approach_ids))
        )
    )

    # Load validation results
    validation_results = list(
        db.scalars(
            select(ValidationResult).where(ValidationResult.approach_id.in_(approach_ids))
        )
    )

    # Load experiments that reference any of these approaches
    all_experiments = list(
        db.scalars(
            select(ExperimentCard).where(ExperimentCard.workspace_id == goal_id)
        )
    )
    linked_experiments = [
        e for e in all_experiments
        if any(aid in json.loads(e.approach_ids or "[]") for aid in approach_ids)
    ]

    approaches_context = [
        _build_approach_context(a, scores, linked_experiments, validation_results)
        for a in approaches
    ]

    agent_concepts = _run_device_agent(goal, approaches_context)

    generation_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Collect experiment and validation IDs for traceability
    all_exp_ids = [e.id for e in linked_experiments]
    all_val_ids = [v.id for v in validation_results]

    cards = []
    for concept in agent_concepts:
        card = DeviceConceptCard(
            id=str(uuid.uuid4()),
            workspace_id=goal_id,
            name=concept.name,
            description=concept.description or None,
            status="generated",
            maturity=concept.maturity,
            form_factor=json.dumps(concept.form_factor.model_dump()),
            use_case=json.dumps(concept.use_case.model_dump()),
            acoustic_architecture=json.dumps(concept.acoustic_architecture.model_dump()),
            hardware=json.dumps(concept.hardware.model_dump()),
            expected_performance=json.dumps(concept.expected_performance.model_dump()),
            approach_ids=json.dumps(approach_ids),
            experiment_ids=json.dumps(all_exp_ids),
            validation_result_ids=json.dumps(all_val_ids),
            unresolved_risks=json.dumps(concept.unresolved_risks),
            next_steps=json.dumps(concept.next_steps),
            rationale=concept.rationale or None,
            model_used=settings.validation_model,
            generation_run_id=generation_run_id,
            created_at=now,
            updated_at=now,
        )
        db.add(card)
        cards.append(card)

    db.commit()
    for card in cards:
        db.refresh(card)

    return DeviceConceptGenerateResponse(
        generated=len(cards),
        generation_run_id=generation_run_id,
        items=[_to_response(c) for c in cards],
    )


def get(db: Session, device_id: str, goal_id: str) -> DeviceConceptCardResponse:
    card = _get_or_404(db, device_id, goal_id)
    return _to_response(card)


def list_devices(
    db: Session,
    goal_id: str,
    status: DeviceConceptStatusEnum | None = None,
    skip: int = 0,
    limit: int = 20,
) -> DeviceConceptCardListResponse:
    stmt = (
        select(DeviceConceptCard)
        .where(DeviceConceptCard.workspace_id == goal_id)
        .order_by(DeviceConceptCard.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(DeviceConceptCard.status == status.value)

    all_cards = list(db.scalars(stmt))
    total = len(all_cards)
    page = all_cards[skip : skip + limit]
    return DeviceConceptCardListResponse(items=[_to_response(c) for c in page], total=total)


def transition(
    db: Session,
    device_id: str,
    goal_id: str,
    new_status: DeviceConceptStatusEnum,
) -> DeviceConceptCardResponse:
    card = _get_or_404(db, device_id, goal_id)
    current = DeviceConceptStatusEnum(card.status)
    allowed = ALLOWED_TRANSITIONS[current]
    if new_status not in allowed:
        allowed_vals = sorted(s.value for s in allowed)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition from {current.value!r} to {new_status.value!r}. "
                f"Allowed: {allowed_vals or 'none (terminal state)'}"
            ),
        )
    card.status = new_status.value
    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def compare(
    db: Session,
    goal_id: str,
    device_ids: list[str],
) -> DeviceConceptComparisonResponse:
    if len(device_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 device IDs required for comparison")

    cards = [_get_or_404(db, did, goal_id) for did in device_ids]

    dimensions = [
        "form_factor_type",
        "maturity",
        "approach_count",
        "experiment_count",
        "validation_result_count",
        "unresolved_risk_count",
        "next_step_count",
    ]

    concepts = []
    for card in cards:
        ff = json.loads(card.form_factor) if card.form_factor else {}
        concepts.append(
            DeviceConceptComparisonItem(
                id=card.id,
                name=card.name,
                values={
                    "form_factor_type": ff.get("type", ""),
                    "maturity": card.maturity,
                    "approach_count": str(len(json.loads(card.approach_ids or "[]"))),
                    "experiment_count": str(len(json.loads(card.experiment_ids or "[]"))),
                    "validation_result_count": str(len(json.loads(card.validation_result_ids or "[]"))),
                    "unresolved_risk_count": str(len(json.loads(card.unresolved_risks or "[]"))),
                    "next_step_count": str(len(json.loads(card.next_steps or "[]"))),
                },
            )
        )

    return DeviceConceptComparisonResponse(dimensions=dimensions, concepts=concepts)


def export_device(
    db: Session,
    device_id: str,
    goal_id: str,
    fmt: str = "markdown",
) -> DeviceConceptExportResponse:
    card = _get_or_404(db, device_id, goal_id)
    resp = _to_response(card)

    if fmt == "json":
        content = resp.model_dump_json(indent=2)
    else:
        lines = [f"# {resp.name}"]
        if resp.description:
            lines += ["", f"## Overview", "", resp.description]
        if resp.rationale:
            lines += ["", "## Rationale", "", resp.rationale]
        lines += [
            "",
            "## Form Factor",
            "",
            f"- **Type**: {resp.form_factor.type}",
            f"- **Placement**: {resp.form_factor.placement}",
            f"- **Listener distance**: {resp.form_factor.listener_distance_cm}",
        ]
        uc = resp.use_case
        lines += [
            "",
            "## Use Case",
            "",
            f"- **Primary**: {uc.primary}",
        ]
        if uc.secondary:
            lines += ["- **Secondary**:"] + [f"  - {s}" for s in uc.secondary]
        aa = resp.acoustic_architecture
        lines += ["", "## Acoustic Architecture", ""]
        if aa.control_stack:
            lines += ["**Control stack**:"] + [f"- {s}" for s in aa.control_stack]
        if aa.calibration:
            lines += ["", "**Calibration**:"] + [f"- {s}" for s in aa.calibration]
        if aa.simulation_backing:
            lines += ["", "**Simulation backing**:"] + [f"- {s}" for s in aa.simulation_backing]
        hw = resp.hardware
        lines += ["", "## Hardware", ""]
        if hw.speakers:
            lines.append(f"**Speakers**: {json.dumps(hw.speakers)}")
        if hw.microphones:
            lines.append(f"**Microphones**: {json.dumps(hw.microphones)}")
        if hw.compute:
            lines.append(f"**Compute**: {json.dumps(hw.compute)}")
        ep = resp.expected_performance
        lines += [
            "",
            "## Expected Performance",
            "",
            f"- **Bright zone**: {ep.bright_zone}",
            f"- **Dark zone**: {ep.dark_zone}",
            f"- **Latency**: {ep.latency}",
            f"- **Robustness**: {ep.robustness}",
        ]
        lines += [
            "",
            f"## Supporting Approaches ({len(resp.approach_ids)})",
            "",
        ] + [f"- {aid}" for aid in resp.approach_ids]
        if resp.unresolved_risks:
            lines += ["", "## Unresolved Risks", ""] + [f"- {r}" for r in resp.unresolved_risks]
        if resp.next_steps:
            lines += ["", "## Next Steps", ""] + [f"1. {s}" for s in resp.next_steps]
        content = "\n".join(lines)

    return DeviceConceptExportResponse(device_id=device_id, format=fmt, content=content)


def delete(db: Session, device_id: str, goal_id: str) -> None:
    card = _get_or_404(db, device_id, goal_id)
    if card.status != DeviceConceptStatusEnum.generated.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete device concept in status {card.status!r}; only 'generated' can be deleted",
        )
    db.delete(card)
    db.commit()
