import json
import math
import re
import time
import uuid
from datetime import datetime, timezone
from itertools import product

import anthropic
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.clients.repro import ReproClient
from coscientist.config import settings
from coscientist.llm import anthropic_client
from coscientist.models.approach import ApproachCard
from coscientist.models.device import DeviceConceptCard
from coscientist.models.experiment import ExperimentCard
from coscientist.models.score import RubricScore
from coscientist.models.validation import ValidationResult
from coscientist.schemas.device import (
    GEOMETRY_SIM_KEYS,
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
    DeviceGeometry,
    DeviceOptimizeCandidate,
    DeviceOptimizeResult,
    GeometryClamp,
    DeviceReproductionResult,
    DeviceReproductionSweepCandidate,
    DeviceReproductionSweepResult,
    DeviceSimulationResult,
    ExpectedPerformance,
    FormFactor,
    HardwareSpec,
    ReproductionPerBand,
    SimulationPerBand,
    UseCase,
)
from coscientist.services import device_evidence as device_evidence_svc
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc

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
    geo_raw = json.loads(card.geometry) if card.geometry else {}

    return DeviceConceptCardResponse(
        id=card.id,
        workspace_id=card.workspace_id,
        name=card.name,
        description=card.description,
        status=DeviceConceptStatusEnum(card.status),
        maturity=card.maturity,
        confidence=card.confidence,
        form_factor=FormFactor(**ff_raw),
        use_case=UseCase(**uc_raw),
        acoustic_architecture=AcousticArchitecture(**aa_raw),
        hardware=HardwareSpec(**hw_raw),
        expected_performance=ExpectedPerformance(**ep_raw),
        geometry=DeviceGeometry(**geo_raw),
        approach_ids=json.loads(card.approach_ids) if card.approach_ids else [],
        experiment_ids=json.loads(card.experiment_ids) if card.experiment_ids else [],
        validation_result_ids=json.loads(card.validation_result_ids) if card.validation_result_ids else [],
        unresolved_risks=json.loads(card.unresolved_risks) if card.unresolved_risks else [],
        next_steps=json.loads(card.next_steps) if card.next_steps else [],
        rationale=card.rationale,
        model_used=card.model_used,
        generation_run_id=card.generation_run_id,
        simulation=json.loads(card.simulation) if card.simulation else {},
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


# The geometry block is what actually gets simulated, so the agent has to be
# taught the frame, the units, and what each knob physically buys — otherwise it
# emits plausible-looking numbers that all resolve to the same device.
_GEOMETRY_PROMPT = """GEOMETRY — the sim-ready block (required on every concept)
----------------------------------------------------------
Every other field on the card is prose for a human. "geometry" is the numeric spec
that actually gets simulated, so it must be physically committed, not hedged.

Coordinate frame: metres. The array face sits at the local origin and its boresight
points along +y. x is lateral, z is vertical. A listener at [0, 0.6, 0] is 60 cm
straight ahead of the array; a dark zone at [0.4, 0.6, 0] is a second person 40 cm
to the side at the same distance.

Emit only the keys your concept actually commits to — anything you omit keeps the
simulator default. Do NOT emit "positions" or "normals"; choose a layout instead.

  layout            "cap" | "planar" | "ula" | "ring" — the array topology.
                    ula    one horizontal line of elements, all facing +y. Cheapest
                           to build; steering in azimuth only.
                    planar square grid in the x-z plane, all facing +y. Adds
                           elevation control at the cost of element count.
                    cap    elements on a spherical cap opening toward +y, each facing
                           radially outward so they splay off boresight. Buys angular
                           diversity inside a compact aperture.
                    ring   modules on a horizontal ring centred on the listener, each
                           aimed inward. Diversity comes from azimuthal separation
                           rather than one aperture — the tabletop or room-periphery
                           deployment. ring_radius and listener interact: the ring is
                           built around the listener point.
  n_elements        4-64. Degrees of freedom for the contrast solver, and the dominant
                    cost, power and calibration driver of the real build.
  pitch             element spacing in metres for ula/planar. Above half a wavelength
                    at your top band edge (about 21 mm at 8 kHz) grating lobes appear;
                    below about 8 mm the elements physically collide.
  cap_radius        sphere radius in metres for "cap". Smaller radius = tighter
                    curvature = wider angular splay for the same element count.
  cap_deg           cap half-angle in degrees. 5 is effectively flat; 80 wraps the
                    outer elements nearly sideways.
  ring_radius       radius in metres of the ring of modules around the listener.
  listener          [x, y, z] centre of the bright zone. y is the boresight distance
                    and is the single most consequential number on the card — it must
                    agree with form_factor.listener_distance_cm.
  dark              [x, y, z] centre of the zone to keep quiet. Its offset from
                    "listener" is the separation the device must achieve: 0.4 m is a
                    neighbouring seat, 1.5 m is across a desk. Zones must not overlap.
  zone_half_extent  half-width in metres of each cubic zone. 0.09 is roughly one head.
                    Larger means holding contrast over a moving listener, which is a
                    much harder problem — only widen it if the concept claims it.
  freqs             1-8 audio frequencies in Hz to evaluate. PAL devices are weakest at
                    the low end; include the lowest frequency your concept claims.
  room_dims         [Lx, Ly, Lz] in metres of the enclosing room.
  t60               reverberation time in seconds. 0 is the anechoic upper bound, 0.4 a
                    small treated office, 0.8+ a hard-surfaced room where reflections
                    wreck contrast. Pick the room the concept is actually for.
  pal_model         true for a parametric-array (ultrasonic, self-demodulating)
                    loudspeaker, false for conventional direct-radiating drivers. This
                    changes the physics, not just a constant — set it false if your
                    concept is a conventional multi-driver array.
  carrier           PAL ultrasonic carrier in Hz, 20000-80000. 40000 is typical.
  aperture          PAL element aperture radius in metres. A larger aperture narrows the
                    demodulated beam (more contrast) but makes each element physically
                    bigger, which constrains pitch.
  sidelobe_floor    off-axis amplitude floor as a linear ratio. 0.056 (-25 dB) is what
                    real PAL hardware measures; use a lower value only if the concept
                    explicitly claims better off-axis suppression, and say so in
                    design_intent.
  nearfield_length  Berktay beam-formation length in metres — the distance over which
                    the demodulated beam narrows. 0.4 is typical; raise it toward your
                    listener distance for an explicitly near-field concept.
  design_intent     one sentence naming the physical trade this geometry makes, e.g.
                    "few elements on a wide cap to buy angular diversity without a
                    large aperture".

Make the concepts PHYSICALLY DIFFERENT from each other, not one array with the element
count jiggled. Any two concepts must differ in at least two of: layout, aperture scale
(pitch / cap_radius / ring_radius), listener distance, zone separation, and pal_model.
If two approaches differ only in their control algorithm, that is ONE device concept —
merge them and say so in the rationale. Every number must follow from the approaches and
device constraints you were given; if you have no basis for a knob, omit it rather than
inventing a value."""


def _run_device_agent(
    db: Session,
    goal_id: str,
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
        '  "geometry": {...} — the sim-ready numeric spec, see GEOMETRY below\n'
        '  "unresolved_risks": [str, ...] — list of open technical risks\n'
        '  "next_steps": [str, ...] — list of recommended next experiments or prototyping steps\n\n'
        "Propose one device concept per distinct form factor you identify as viable. "
        "Maturity is determined by the weakest validated approach: if any approach is theoretical, the device is theoretical.\n\n"
        + _GEOMETRY_PROMPT
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

    client = anthropic_client()
    start = time.monotonic()
    message = client.messages.create(
        model=settings.validation_model,
        # The geometry block adds ~18 keys per concept and overflow here is a hard
        # 502 for the whole batch, not a partial result.
        max_tokens=16384,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    raw = message.content[0].text.strip()
    governance_svc.log_agent_call(
        db=db,
        workspace_id=goal_id,
        service="device",
        action="generate_device_concepts",
        model_used=settings.validation_model,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        elapsed_ms=elapsed_ms,
        response_summary=raw[:512],
    )
    if message.stop_reason == "max_tokens":
        raise HTTPException(
            status_code=502,
            detail=(
                "Device agent response was truncated (hit max_tokens). "
                "The JSON array is incomplete; retry or reduce the number of concepts."
            ),
        )
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
    goal_svc.raise_if_restricted(db, goal_id)
    goal = goal_svc.get(db, goal_id)

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

    agent_concepts = _run_device_agent(db, goal_id, goal, approaches_context)

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
            geometry=json.dumps(_clamp_geometry(concept.geometry).model_dump()),
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


# ---------------------------------------------------------------------------
# CS-EPIC-DEVICE: geometry simulation (spec→model bridge)
# ---------------------------------------------------------------------------

# Acoustic-contrast bar a PSZ device is designed to clear (dB). The generator
# doesn't stamp a per-card pass condition, so this is the shared design target.
DEFAULT_TARGET_CONTRAST_DB = 15.0


def _first_number(text: str, default: float) -> float:
    """First numeric value in a free-text field (e.g. '50-200' → 50.0)."""
    if not text:
        return default
    m = re.search(r"-?\d+(?:\.\d+)?", str(text))
    return float(m.group()) if m else default


def _infer_layout(geometry_text: str) -> str:
    """Map the card's free-text speaker geometry to a simulator layout keyword."""
    g = (geometry_text or "").lower()
    if any(w in g for w in ("ring", "periphery", "azimuth", "distributed", "surround")):
        return "ring"
    if any(w in g for w in ("cap", "curv", "spher", "dome", "hemis")):
        return "cap"
    if any(w in g for w in ("line", "linear", "ula", "row", "1d")):
        return "ula"
    if any(w in g for w in ("planar", "grid", "flat", "panel", "matrix", "2d")):
        return "planar"
    return "cap"  # a curved PAL cap is the card's own leading option


# Geometry knobs a user may override to refine a device (mirrors repro's
# DeviceGeometryRequest fields). Anything outside this set is rejected so a typo
# can't silently no-op. Explicit element coordinates are override-only — the
# agent picks a layout instead.
ALLOWED_OVERRIDE_KEYS = GEOMETRY_SIM_KEYS | {"positions", "normals"}


def _apply_overrides(geometry: dict, overrides: dict | None) -> dict:
    """Merge user overrides onto a resolved geometry so the refine loop — change a
    knob, re-simulate, see the number move — is real. Unknown keys raise ValueError
    (→ 400) rather than being silently ignored."""
    if not overrides:
        return geometry
    unknown = set(overrides) - ALLOWED_OVERRIDE_KEYS
    if unknown:
        raise ValueError(
            f"unknown geometry override(s): {sorted(unknown)}; "
            f"allowed: {sorted(ALLOWED_OVERRIDE_KEYS)}"
        )
    geometry.update(overrides)
    return geometry


_DARK_OFFSET_X = 0.40  # adjacent listener, 40 cm off boresight

_LAYOUTS = ("cap", "planar", "ula", "ring")

# What repro's simulator can meaningfully handle. The agent is asked for
# physically motivated numbers, not sim-safe ones, so a proposal is clamped into
# this envelope when it is *persisted* and every adjustment is recorded on the
# card. Explicit human overrides at simulate time are NOT clamped — that is the
# deliberate escape hatch for probing outside the envelope.
GEOMETRY_BOUNDS: dict[str, tuple[float, float, str]] = {
    "n_elements": (4, 64, "under 4 elements there are too few DOF to steer; over 64 the image-source room build dominates runtime"),
    "cap_radius": (0.03, 0.60, "a spherical cap under 3 cm cannot hold elements; over 60 cm stops being a device"),
    "cap_deg": (5.0, 80.0, "under 5 deg the cap degenerates to planar; over 80 deg the outer elements face away from the listener"),
    "ring_radius": (0.10, 2.00, "ring modules must sit outside the listener zone and inside the room"),
    "pitch": (0.005, 0.10, "5 mm is physical element collision; 100 mm is deep grating-lobe territory"),
    "zone_half_extent": (0.02, 0.40, "under 2 cm is sub-head; over 40 cm is not a personal zone"),
    "t60": (0.0, 2.0, "0 is the anechoic bound; over 2 s the image-source truncation is no longer valid"),
    "carrier": (20000.0, 80000.0, "usable PAL ultrasonic carrier band"),
    "aperture": (0.002, 0.05, "PAL element aperture radius; sets the Berktay beamwidth"),
    "sidelobe_floor": (0.001, 0.5, "off-axis amplitude floor; 0.056 (-25 dB) is what real PAL hardware measures"),
    "nearfield_length": (0.0, 3.0, "Berktay beam-formation length; 0 disables the near-field taper"),
}

_FREQ_BOUNDS = (100.0, 20000.0)
_ROOM_DIM_BOUNDS = (1.0, 20.0)
_MAX_FREQS = 8


def _clamp_scalar(key: str, value, clamps: list[GeometryClamp]):
    lo, hi, reason = GEOMETRY_BOUNDS[key]
    applied = max(lo, min(hi, value))
    if isinstance(value, int):
        applied = int(applied)
    if applied != value:
        clamps.append(GeometryClamp(
            key=key, proposed=value, applied=applied, bound=f"{lo}..{hi}", reason=reason,
        ))
    return applied


def _clean_vector(key: str, value, clamps: list[GeometryClamp], lo: float, hi: float):
    """Three finite numbers or nothing — a malformed vector would 422 at repro."""
    try:
        vec = [float(v) for v in value]
    except (TypeError, ValueError):
        vec = []
    if len(vec) != 3 or any(v != v or v in (float("inf"), float("-inf")) for v in vec):
        clamps.append(GeometryClamp(
            key=key, proposed=value, applied=None, bound="3 finite numbers",
            reason="dropped; the simulator needs an [x, y, z] point in metres",
        ))
        return None
    applied = [max(lo, min(hi, v)) for v in vec]
    if applied != vec:
        clamps.append(GeometryClamp(
            key=key, proposed=vec, applied=applied, bound=f"each {lo}..{hi} m",
            reason="point must sit inside the simulated room",
        ))
    return applied


def _clamp_geometry(geo: DeviceGeometry) -> DeviceGeometry:
    """Pull an agent-proposed geometry into the simulator envelope, recording every
    adjustment on the block so an edit is visible rather than silent. Applied on
    persistence only; re-clamping on read would let `clamped` drift out of sync
    with the geometry actually simulated."""
    values = geo.model_dump()
    clamps: list[GeometryClamp] = []

    for key in GEOMETRY_BOUNDS:
        if values.get(key) is not None:
            values[key] = _clamp_scalar(key, values[key], clamps)

    layout = values.get("layout")
    if layout is not None and layout not in _LAYOUTS:
        applied = _infer_layout(str(layout))
        clamps.append(GeometryClamp(
            key="layout", proposed=layout, applied=applied,
            bound="one of: " + " | ".join(_LAYOUTS),
            reason="unrecognised topology mapped to the nearest simulator layout",
        ))
        values["layout"] = applied

    for key in ("listener", "dark", "array_origin"):
        if values.get(key) is not None:
            values[key] = _clean_vector(key, values[key], clamps, -3.0, 3.0)
    if values.get("listener") is not None:
        # Boresight distance: inside the array's near field is meaningless.
        y = max(0.1, min(3.0, values["listener"][1]))
        if y != values["listener"][1]:
            clamps.append(GeometryClamp(
                key="listener", proposed=values["listener"], applied=[values["listener"][0], y, values["listener"][2]],
                bound="boresight 0.1..3.0 m",
                reason="listener must sit in front of the array and inside the room",
            ))
            values["listener"][1] = y

    if values.get("freqs") is not None:
        values["freqs"] = _clean_freqs(values["freqs"], clamps)
    if values.get("room_dims") is not None:
        values["room_dims"] = _clean_vector(
            "room_dims", values["room_dims"], clamps, *_ROOM_DIM_BOUNDS
        )

    _separate_zones(values, clamps)

    values["clamped"] = [c.model_dump() for c in clamps]
    return DeviceGeometry(**values)


def _clean_freqs(value, clamps: list[GeometryClamp]) -> list[float] | None:
    numeric = []
    for f in value if isinstance(value, (list, tuple)) else []:
        try:
            numeric.append(float(f))
        except (TypeError, ValueError):
            continue
    applied = sorted({max(_FREQ_BOUNDS[0], min(_FREQ_BOUNDS[1], f)) for f in numeric})[:_MAX_FREQS]
    if not applied:
        clamps.append(GeometryClamp(
            key="freqs", proposed=value, applied=None, bound="1..8 values in 100..20000 Hz",
            reason="dropped; no usable audio frequencies",
        ))
        return None
    if applied != [float(f) for f in numeric]:
        clamps.append(GeometryClamp(
            key="freqs", proposed=value, applied=applied,
            bound=f"1..{_MAX_FREQS} values in {_FREQ_BOUNDS[0]}..{_FREQ_BOUNDS[1]} Hz",
            reason="evaluation band normalised: in-band, deduped, sorted, truncated",
        ))
    return applied


def _separate_zones(values: dict, clamps: list[GeometryClamp]) -> None:
    """Overlapping bright and dark cubes make contrast physically undefined, so
    push the dark zone out along the axis where it is already furthest away."""
    listener, dark = values.get("listener"), values.get("dark")
    half = values.get("zone_half_extent") or _default_geometry()["zone_half_extent"]
    if listener is None or dark is None:
        return
    deltas = [d - l for l, d in zip(listener, dark)]
    if max(abs(d) for d in deltas) >= 2 * half:
        return
    axis = max(range(3), key=lambda i: abs(deltas[i]))
    sign = 1.0 if deltas[axis] >= 0 else -1.0
    applied = list(dark)
    applied[axis] = listener[axis] + sign * 2 * half
    clamps.append(GeometryClamp(
        key="dark", proposed=dark, applied=applied, bound=f">= {2 * half} m from listener",
        reason="bright and dark zones overlapped; contrast is undefined for overlapping zones",
    ))
    values["dark"] = applied


def _default_geometry() -> dict:
    """Layer 1: the simulator's own defaults. A function, not a module constant —
    callers mutate the returned dict via _apply_overrides, so one simulate with
    overrides would otherwise poison every later resolution in the process."""
    return {
        "layout": "cap",
        "n_elements": 12,
        "cap_radius": 0.12,
        "cap_deg": 35.0,
        "ring_radius": 0.30,
        "pitch": 0.03,
        "listener": [0.0, 1.0, 0.0],
        "dark": [_DARK_OFFSET_X, 1.0, 0.0],
        "zone_half_extent": 0.09,
        "freqs": [2000.0, 4000.0, 6000.0, 8000.0],  # PAL effective audio band
        "room_dims": [4.0, 4.0, 2.6],               # small desktop room
        "t60": 0.4,
        "pal_model": True,                          # PAL nonlinear demodulation
        "carrier": 40000.0,
        "aperture": 0.01,
        "sidelobe_floor": 0.056,                    # -25 dB off-axis (realistic PAL)
        "nearfield_length": 0.4,                    # beam-formation length z_form (m)
    }


def _legacy_geometry(card: DeviceConceptCard) -> dict:
    """Layer 2: knobs inferred from the card's prose, for cards generated before
    the structured geometry block existed. This is deliberately frozen — cards in
    the live DB depend on resolving exactly as they always have."""
    hw = json.loads(card.hardware) if card.hardware else {}
    ff = json.loads(card.form_factor) if card.form_factor else {}

    speakers = hw.get("speakers", {}) if isinstance(hw, dict) else {}
    count = speakers.get("estimated_count")
    try:
        n_elements = int(count) if count is not None else 12
    except (TypeError, ValueError):
        n_elements = int(_first_number(str(count), 12))
    n_elements = max(4, min(32, n_elements))

    # Listener distance (cm range → boresight distance in metres), clamped sane.
    dist_cm = _first_number(ff.get("listener_distance_cm", ""), 100.0)
    listener_y = max(0.3, min(3.0, dist_cm / 100.0))

    return {
        "layout": _infer_layout(str(speakers.get("geometry", ""))),
        "n_elements": n_elements,
        "listener": [0.0, listener_y, 0.0],
        "dark": [_DARK_OFFSET_X, listener_y, 0.0],
    }


def _card_geometry(card: DeviceConceptCard) -> dict:
    """Layer 3: the card's own sim-ready geometry block, only the knobs it set."""
    try:
        raw = json.loads(getattr(card, "geometry", None) or "{}")
    except (ValueError, TypeError):
        return {}
    if not raw:
        return {}

    fields = DeviceGeometry(**raw).sim_fields()
    # Moving the listener without saying where the dark zone went would leave the
    # legacy layer's dark zone pinned at the old boresight distance.
    if "listener" in fields and "dark" not in fields:
        lx, ly, lz = fields["listener"]
        fields["dark"] = [lx + _DARK_OFFSET_X, ly, lz]
    return fields


def _resolve_geometry(card: DeviceConceptCard) -> dict:
    """Resolve a DeviceConceptCard into a concrete DeviceGeometryRequest for the
    simulator. Layered, later wins: simulator defaults → prose inference → the
    card's geometry block. Caller overrides are the final layer, applied by
    _apply_overrides at the call site. Deterministic: same card → same geometry."""
    geometry = _default_geometry()
    geometry.update(_legacy_geometry(card))
    geometry.update(_card_geometry(card))
    return geometry


_UNSET = "—"


def _simulated_geometry(card: DeviceConceptCard, sim: dict) -> dict:
    """The geometry the card's last simulation actually ran on: the resolved block
    plus the overrides that run carried. Re-resolved rather than read out of
    `sim["resolved_geometry"]`, because repro's *response* renames keys
    (`listener_m`, `cap_radius_m`, `freqs_hz`) while its request does not."""
    geometry = _resolve_geometry(card)
    try:
        return _apply_overrides(geometry, sim.get("overrides"))
    except ValueError:
        # A blob written before a knob was renamed out of the allowlist; the base
        # resolution is still the honest answer.
        return geometry


def _boresight_distance(geometry: dict) -> float | None:
    listener = geometry.get("listener")
    if isinstance(listener, (list, tuple)) and len(listener) == 3:
        return float(listener[1])
    return None


def _zone_separation(geometry: dict) -> float | None:
    """Euclidean distance between bright and dark zone centres — the separation the
    device has to achieve, and the single number that makes two concepts comparable."""
    listener, dark = geometry.get("listener"), geometry.get("dark")
    if not (isinstance(listener, (list, tuple)) and isinstance(dark, (list, tuple))):
        return None
    if len(listener) != 3 or len(dark) != 3:
        return None
    return math.dist([float(v) for v in listener], [float(v) for v in dark])


def _fmt_m(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else _UNSET


def simulate(
    db: Session,
    device_id: str,
    goal_id: str,
    *,
    timeout: float | None = None,
    overrides: dict | None = None,
) -> DeviceSimulationResult:
    """Predict a device concept's acoustic contrast by resolving its geometry and
    handing it to repro's device-sim endpoint (co-scientist holds no numpy). Writes
    the prediction onto the card so the refine loop — edit geometry, re-simulate —
    is a first-class feature. Idempotent-ish: re-running overwrites the prediction.

    `overrides` lets the caller refine specific resolved knobs (element count, layout,
    aperture, listener distance, ...); the prior prediction's contrast is returned as
    `previous_contrast_db` so a re-run shows the delta the refinement produced."""
    governance_svc.assert_execution_boundary("simulate device geometries")
    goal_svc.raise_if_restricted(db, goal_id)

    card = _get_or_404(db, device_id, goal_id)

    previous_contrast_db: float | None = None
    if card.simulation:
        try:
            previous_contrast_db = json.loads(card.simulation).get("acoustic_contrast_db")
        except (ValueError, TypeError):
            previous_contrast_db = None

    geometry = _apply_overrides(_resolve_geometry(card), overrides)

    client = ReproClient(timeout=timeout or settings.repro_run_timeout)
    try:
        result = client.simulate_device(geometry)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim rejected the geometry ({exc.response.status_code}): "
            f"{exc.response.text[:300]}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim unreachable at {settings.repro_url}: {exc}",
        )
    finally:
        client.close()

    contrast = float(result.get("acoustic_contrast_db", 0.0))
    per_band = result.get("per_band", [])
    target = DEFAULT_TARGET_CONTRAST_DB
    simulated_at = datetime.now(timezone.utc)

    card.simulation = json.dumps(
        {
            "simulated_at": simulated_at.isoformat(),
            "acoustic_contrast_db": contrast,
            "per_band": per_band,
            "target_contrast_db": target,
            "meets_target": contrast >= target,
            "resolved_geometry": result.get("resolved_geometry", geometry),
            "model_flags": result.get("model_flags", {}),
            "approximations": result.get("approximations", []),
            "repro_endpoint": f"{settings.repro_url.rstrip('/')}/api/v1/device-sim",
            "overrides": overrides or {},
            "previous_contrast_db": previous_contrast_db,
        }
    )
    card.updated_at = simulated_at
    db.commit()
    db.refresh(card)

    return DeviceSimulationResult(
        device_id=device_id,
        simulated_at=simulated_at,
        acoustic_contrast_db=contrast,
        per_band=[SimulationPerBand(**b) for b in per_band],
        target_contrast_db=target,
        meets_target=contrast >= target,
        resolved_geometry=result.get("resolved_geometry", geometry),
        model_flags=result.get("model_flags", {}),
        approximations=result.get("approximations", []),
        repro_endpoint=f"{settings.repro_url.rstrip('/')}/api/v1/device-sim",
        overrides=overrides or {},
        previous_contrast_db=previous_contrast_db,
        clamped=_card_clamps(card),
    )


def _card_clamps(card: DeviceConceptCard) -> list[GeometryClamp]:
    try:
        raw = json.loads(getattr(card, "geometry", None) or "{}")
    except (ValueError, TypeError):
        return []
    return DeviceGeometry(**raw).clamped if raw else []


def reproduce(
    db: Session,
    device_id: str,
    goal_id: str,
    *,
    timeout: float | None = None,
    overrides: dict | None = None,
    target_kind: str = "spherical_wave",
    target_origin: list[float] | None = None,
    target_direction: list[float] | None = None,
    solver: str = "pressure_matching",
    regularization: float = 1e-3,
    control_grid_n: int = 4,
    eval_grid_n: int = 5,
) -> DeviceReproductionResult:
    """Predict sound-field reproduction quality for a device concept.

    This uses the same resolved geometry as `simulate`, but asks repro to solve
    pressure matching against a target pressure field and return reproduction
    fidelity metrics instead of only an acoustic-contrast optimum.
    """
    governance_svc.assert_execution_boundary("simulate sound-field reproduction")
    goal_svc.raise_if_restricted(db, goal_id)

    card = _get_or_404(db, device_id, goal_id)

    previous_nre: float | None = None
    if card.simulation:
        try:
            previous_nre = json.loads(card.simulation).get("normalized_reproduction_error")
        except (ValueError, TypeError):
            previous_nre = None

    request = _apply_overrides(_resolve_geometry(card), overrides)
    request.update(
        {
            "solver": solver,
            "target_kind": target_kind,
            "regularization": regularization,
            "control_grid_n": control_grid_n,
            "eval_grid_n": eval_grid_n,
        }
    )
    if target_origin is not None:
        request["target_origin"] = target_origin
    if target_direction is not None:
        request["target_direction"] = target_direction

    client = ReproClient(timeout=timeout or settings.repro_run_timeout)
    try:
        result = client.reproduce_device(request)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim/reproduce rejected the request ({exc.response.status_code}): "
            f"{exc.response.text[:300]}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim unreachable at {settings.repro_url}: {exc}",
        )
    finally:
        client.close()

    simulated_at = datetime.now(timezone.utc)
    endpoint = f"{settings.repro_url.rstrip('/')}/api/v1/device-sim/reproduce"
    persisted = {
        "mode": result.get("mode", "sound_field_reproduction"),
        "simulated_at": simulated_at.isoformat(),
        "solver": result.get("solver", solver),
        "target": result.get("target", {}),
        "normalized_reproduction_error": float(result.get("normalized_reproduction_error", 0.0)),
        "spatial_correlation": float(result.get("spatial_correlation", 0.0)),
        "mean_spl_error_db": float(result.get("mean_spl_error_db", 0.0)),
        "max_spl_error_db": float(result.get("max_spl_error_db", 0.0)),
        "array_effort": float(result.get("array_effort", 0.0)),
        "acoustic_contrast_db": float(result.get("acoustic_contrast_db", 0.0)),
        "per_band": result.get("per_band", []),
        "resolved_geometry": result.get("resolved_geometry", request),
        "model_flags": result.get("model_flags", {}),
        "approximations": result.get("approximations", []),
        "repro_endpoint": endpoint,
        "overrides": overrides or {},
        "previous_normalized_reproduction_error": previous_nre,
    }
    card.simulation = json.dumps(persisted)
    card.updated_at = simulated_at
    db.commit()
    db.refresh(card)

    return DeviceReproductionResult(
        device_id=device_id,
        simulated_at=simulated_at,
        mode=persisted["mode"],
        solver=persisted["solver"],
        target=persisted["target"],
        normalized_reproduction_error=persisted["normalized_reproduction_error"],
        spatial_correlation=persisted["spatial_correlation"],
        mean_spl_error_db=persisted["mean_spl_error_db"],
        max_spl_error_db=persisted["max_spl_error_db"],
        array_effort=persisted["array_effort"],
        acoustic_contrast_db=persisted["acoustic_contrast_db"],
        per_band=[ReproductionPerBand(**b) for b in persisted["per_band"]],
        resolved_geometry=persisted["resolved_geometry"],
        model_flags=persisted["model_flags"],
        approximations=persisted["approximations"],
        repro_endpoint=endpoint,
        overrides=overrides or {},
        previous_normalized_reproduction_error=previous_nre,
    )


def reproduce_sweep(
    db: Session,
    device_id: str,
    goal_id: str,
    search_space: dict,
    *,
    max_candidates: int = 24,
    timeout: float | None = None,
    target_kind: str = "spherical_wave",
    target_origin: list[float] | None = None,
    target_direction: list[float] | None = None,
    solver: str = "pressure_matching",
    regularization: float = 1e-3,
    control_grid_n: int = 4,
    eval_grid_n: int = 5,
) -> DeviceReproductionSweepResult:
    """Sweep geometry knobs for pressure-matching reproduction quality.

    Candidates are ranked by lowest normalized reproduction error, because this
    path optimizes target-field fidelity rather than bright/dark contrast.
    """
    governance_svc.assert_execution_boundary("sweep sound-field reproduction")
    goal_svc.raise_if_restricted(db, goal_id)

    if not search_space:
        raise ValueError("search_space is empty; give at least one knob to sweep")
    unknown = set(search_space) - ALLOWED_OVERRIDE_KEYS
    if unknown:
        raise ValueError(
            f"unknown geometry override(s): {sorted(unknown)}; "
            f"allowed: {sorted(ALLOWED_OVERRIDE_KEYS)}"
        )

    keys = list(search_space.keys())
    value_lists: list[list] = []
    for key in keys:
        values = search_space[key]
        if not isinstance(values, list) or not values:
            raise ValueError(f"search_space[{key!r}] must be a non-empty list")
        value_lists.append(values)

    combos = list(product(*value_lists))
    if len(combos) > max_candidates:
        raise ValueError(
            f"search space has {len(combos)} candidates > max_candidates={max_candidates}; "
            "narrow the sweep or raise max_candidates"
        )

    card = _get_or_404(db, device_id, goal_id)
    previous_nre: float | None = None
    if card.simulation:
        try:
            previous_nre = json.loads(card.simulation).get("normalized_reproduction_error")
        except (ValueError, TypeError):
            previous_nre = None

    base = _resolve_geometry(card)
    endpoint = f"{settings.repro_url.rstrip('/')}/api/v1/device-sim/reproduce"
    candidate_rows: list[dict] = []

    client = ReproClient(timeout=timeout or settings.repro_run_timeout)
    try:
        for combo in combos:
            overrides = dict(zip(keys, combo))
            request = _apply_overrides(dict(base), overrides)
            request.update(
                {
                    "solver": solver,
                    "target_kind": target_kind,
                    "regularization": regularization,
                    "control_grid_n": control_grid_n,
                    "eval_grid_n": eval_grid_n,
                }
            )
            if target_origin is not None:
                request["target_origin"] = target_origin
            if target_direction is not None:
                request["target_direction"] = target_direction

            result = client.reproduce_device(request)
            candidate_rows.append(
                {
                    "overrides": overrides,
                    "normalized_reproduction_error": float(
                        result.get("normalized_reproduction_error", 0.0)
                    ),
                    "spatial_correlation": float(result.get("spatial_correlation", 0.0)),
                    "mean_spl_error_db": float(result.get("mean_spl_error_db", 0.0)),
                    "max_spl_error_db": float(result.get("max_spl_error_db", 0.0)),
                    "array_effort": float(result.get("array_effort", 0.0)),
                    "acoustic_contrast_db": float(result.get("acoustic_contrast_db", 0.0)),
                    "per_band": result.get("per_band", []),
                    "resolved_geometry": result.get("resolved_geometry", request),
                    "model_flags": result.get("model_flags", {}),
                    "approximations": result.get("approximations", []),
                    "target": result.get("target", {}),
                    "solver": result.get("solver", solver),
                }
            )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim/reproduce rejected the request ({exc.response.status_code}): "
            f"{exc.response.text[:300]}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim unreachable at {settings.repro_url}: {exc}",
        )
    finally:
        client.close()

    candidate_rows.sort(key=lambda c: c["normalized_reproduction_error"])
    best = candidate_rows[0]
    simulated_at = datetime.now(timezone.utc)
    persisted = {
        "mode": "sound_field_reproduction",
        "simulated_at": simulated_at.isoformat(),
        "solver": best["solver"],
        "target": best["target"],
        "normalized_reproduction_error": best["normalized_reproduction_error"],
        "spatial_correlation": best["spatial_correlation"],
        "mean_spl_error_db": best["mean_spl_error_db"],
        "max_spl_error_db": best["max_spl_error_db"],
        "array_effort": best["array_effort"],
        "acoustic_contrast_db": best["acoustic_contrast_db"],
        "per_band": best["per_band"],
        "resolved_geometry": best["resolved_geometry"],
        "model_flags": best["model_flags"],
        "approximations": best["approximations"],
        "repro_endpoint": endpoint,
        "overrides": best["overrides"],
        "previous_normalized_reproduction_error": previous_nre,
        "reproduction_sweep": {
            "swept_keys": keys,
            "n_candidates": len(candidate_rows),
            "best_overrides": best["overrides"],
            "candidates": candidate_rows,
        },
    }
    card.simulation = json.dumps(persisted)
    card.updated_at = simulated_at
    db.commit()
    db.refresh(card)

    return DeviceReproductionSweepResult(
        device_id=device_id,
        simulated_at=simulated_at,
        mode="sound_field_reproduction",
        solver=best["solver"],
        target=best["target"],
        best_overrides=best["overrides"],
        normalized_reproduction_error=best["normalized_reproduction_error"],
        spatial_correlation=best["spatial_correlation"],
        mean_spl_error_db=best["mean_spl_error_db"],
        max_spl_error_db=best["max_spl_error_db"],
        array_effort=best["array_effort"],
        acoustic_contrast_db=best["acoustic_contrast_db"],
        swept_keys=keys,
        n_candidates=len(candidate_rows),
        candidates=[
            DeviceReproductionSweepCandidate(
                overrides=c["overrides"],
                normalized_reproduction_error=c["normalized_reproduction_error"],
                spatial_correlation=c["spatial_correlation"],
                mean_spl_error_db=c["mean_spl_error_db"],
                max_spl_error_db=c["max_spl_error_db"],
                array_effort=c["array_effort"],
                acoustic_contrast_db=c["acoustic_contrast_db"],
                per_band=[ReproductionPerBand(**b) for b in c["per_band"]],
            )
            for c in candidate_rows
        ],
        resolved_geometry=best["resolved_geometry"],
        model_flags=best["model_flags"],
        repro_endpoint=endpoint,
        previous_normalized_reproduction_error=previous_nre,
    )


def optimize(
    db: Session,
    device_id: str,
    goal_id: str,
    search_space: dict,
    *,
    max_candidates: int = 24,
    timeout: float | None = None,
) -> DeviceOptimizeResult:
    """Sweep candidate geometries around a card's resolved geometry and pick the best.

    `search_space` maps a geometry knob (element count, cap angle, aperture, ...) to a
    list of values to try; repro simulates the cartesian product and ranks by contrast.
    The winning geometry's prediction is written onto the card exactly like `simulate`,
    so an optimize run refines the card in one shot instead of a manual --set sweep. The
    prior prediction's contrast is returned as `previous_contrast_db` to show the gain."""
    governance_svc.assert_execution_boundary("optimize device geometries")
    goal_svc.raise_if_restricted(db, goal_id)

    if not search_space:
        raise ValueError("search_space is empty; give at least one knob to sweep")
    unknown = set(search_space) - ALLOWED_OVERRIDE_KEYS
    if unknown:
        raise ValueError(
            f"unknown geometry override(s): {sorted(unknown)}; "
            f"allowed: {sorted(ALLOWED_OVERRIDE_KEYS)}"
        )

    card = _get_or_404(db, device_id, goal_id)

    previous_contrast_db: float | None = None
    if card.simulation:
        try:
            previous_contrast_db = json.loads(card.simulation).get("acoustic_contrast_db")
        except (ValueError, TypeError):
            previous_contrast_db = None

    base = _resolve_geometry(card)

    client = ReproClient(timeout=timeout or settings.repro_run_timeout)
    try:
        result = client.optimize_device(
            base, search_space, max_candidates=max_candidates
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim/optimize rejected the sweep ({exc.response.status_code}): "
            f"{exc.response.text[:300]}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"repro device-sim unreachable at {settings.repro_url}: {exc}",
        )
    finally:
        client.close()

    best = result.get("best", {})
    contrast = float(result.get("best_contrast_db", best.get("acoustic_contrast_db", 0.0)))
    per_band = best.get("per_band", [])
    best_overrides = result.get("best_overrides", {})
    target = DEFAULT_TARGET_CONTRAST_DB
    simulated_at = datetime.now(timezone.utc)
    endpoint = f"{settings.repro_url.rstrip('/')}/api/v1/device-sim"

    card.simulation = json.dumps(
        {
            "simulated_at": simulated_at.isoformat(),
            "acoustic_contrast_db": contrast,
            "per_band": per_band,
            "target_contrast_db": target,
            "meets_target": contrast >= target,
            "resolved_geometry": best.get("resolved_geometry", base),
            "model_flags": best.get("model_flags", {}),
            "approximations": best.get("approximations", []),
            "repro_endpoint": f"{endpoint}/optimize",
            "overrides": best_overrides,
            "previous_contrast_db": previous_contrast_db,
            "optimization": {
                "swept_keys": result.get("swept_keys", []),
                "n_candidates": result.get("n_candidates", 0),
                "best_overrides": best_overrides,
            },
        }
    )
    card.updated_at = simulated_at
    db.commit()
    db.refresh(card)

    return DeviceOptimizeResult(
        device_id=device_id,
        simulated_at=simulated_at,
        best_contrast_db=contrast,
        best_overrides=best_overrides,
        target_contrast_db=target,
        meets_target=contrast >= target,
        swept_keys=result.get("swept_keys", []),
        n_candidates=result.get("n_candidates", 0),
        rooms_built=result.get("rooms_built", 0),
        candidates=[
            DeviceOptimizeCandidate(
                overrides=c.get("overrides", {}),
                acoustic_contrast_db=c.get("acoustic_contrast_db", 0.0),
                n_elements=c.get("n_elements", 0),
                per_band=[SimulationPerBand(**b) for b in c.get("per_band", [])],
            )
            for c in result.get("candidates", [])
        ],
        resolved_geometry=best.get("resolved_geometry", base),
        model_flags=best.get("model_flags", {}),
        repro_endpoint=f"{endpoint}/optimize",
        previous_contrast_db=previous_contrast_db,
    )


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
        "confidence",
        "layout",
        "n_elements",
        "listener_distance_m",
        "zone_separation_m",
        "predicted_contrast_db",
        "meets_target",
        "approach_count",
        "experiment_count",
        "validation_result_count",
        "validation_passed",
        "validation_failed",
        "unresolved_risk_count",
        "next_step_count",
    ]

    concepts = []
    for card in cards:
        ff = json.loads(card.form_factor) if card.form_factor else {}
        ev = device_evidence_svc.build_execution_evidence(db, card.id)
        sim = json.loads(card.simulation) if card.simulation else {}
        geo = _simulated_geometry(card, sim)
        contrast = sim.get("acoustic_contrast_db")
        concepts.append(
            DeviceConceptComparisonItem(
                id=card.id,
                name=card.name,
                values={
                    "form_factor_type": ff.get("type", ""),
                    "maturity": card.maturity,
                    "layout": str(geo.get("layout", _UNSET)),
                    "n_elements": str(geo.get("n_elements", _UNSET)),
                    "listener_distance_m": _fmt_m(_boresight_distance(geo)),
                    "zone_separation_m": _fmt_m(_zone_separation(geo)),
                    "predicted_contrast_db": (
                        f"{float(contrast):.2f}" if contrast is not None else _UNSET
                    ),
                    "meets_target": (
                        str(bool(sim.get("meets_target")))
                        if sim.get("meets_target") is not None
                        else _UNSET
                    ),
                    "confidence": f"{card.confidence:.2f}",
                    "approach_count": str(len(json.loads(card.approach_ids or "[]"))),
                    "experiment_count": str(len(json.loads(card.experiment_ids or "[]"))),
                    "validation_result_count": str(len(json.loads(card.validation_result_ids or "[]"))),
                    "validation_passed": str(ev.passed_experiments),
                    "validation_failed": str(ev.failed_experiments),
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
    sim = json.loads(card.simulation) if card.simulation else {}
    geo = _simulated_geometry(card, sim)

    if fmt == "json":
        payload = json.loads(resp.model_dump_json())
        # The resolved block is what someone would actually build or re-simulate;
        # the card's own geometry block is only the subset it chose to pin.
        payload["resolved_geometry"] = geo
        content = json.dumps(payload, indent=2)
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
        lines += ["", "## Resolved Geometry", ""]
        if resp.geometry.design_intent:
            lines += [f"*{resp.geometry.design_intent}*", ""]
        lines += [f"- **{k}**: {json.dumps(v)}" for k, v in sorted(geo.items())]
        lines.append(f"- **zone_separation_m**: {_fmt_m(_zone_separation(geo))}")
        for clamp in resp.geometry.clamped:
            lines.append(
                f"> Clamped `{clamp.key}`: {json.dumps(clamp.proposed)} → "
                f"{json.dumps(clamp.applied)} ({clamp.bound}) — {clamp.reason}"
            )
        if sim.get("acoustic_contrast_db") is not None:
            lines += [
                "",
                "## Predicted Performance",
                "",
                f"- **Acoustic contrast**: {float(sim['acoustic_contrast_db']):.2f} dB",
            ]
            if sim.get("target_contrast_db") is not None:
                verdict = "meets" if sim.get("meets_target") else "below"
                lines.append(
                    f"- **Target**: {float(sim['target_contrast_db']):.0f} dB ({verdict})"
                )
            if sim.get("mode") == "sound_field_reproduction":
                lines += [
                    f"- **Normalized reproduction error**: {sim.get('normalized_reproduction_error')}",
                    f"- **Spatial correlation**: {sim.get('spatial_correlation')}",
                ]
            if sim.get("overrides"):
                lines.append(
                    "- **Overrides applied**: "
                    + ", ".join(f"`{k}={v}`" for k, v in sorted(sim["overrides"].items()))
                )
            for note in sim.get("approximations", []):
                lines.append(f"- *Approximation*: {note}")
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
