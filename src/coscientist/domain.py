"""
PSZ domain keyword dictionaries for evidence classification.
Falls back to hardcoded dicts when no DB terms are provided.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coscientist.models.ontology import OntologyRelationship, OntologyTerm

_CATEGORY_TO_FIELD = {
    "method": "method_families",
    "metric": "metrics",
    "hardware": "hardware",
    "failure_mode": "failure_modes",
    "acoustic_goal": "acoustic_goals",
    "scene_assumption": "scene_assumptions",
}

METHOD_FAMILIES: dict[str, list[str]] = {
    "acoustic_contrast_control": [
        "acoustic contrast control",
        "acoustic contrast maximization",
        "acc method",
    ],
    "pressure_matching": [
        "pressure matching",
        "pressure matching method",
        "pm method",
    ],
    "beamforming": [
        "beamforming",
        "beam forming",
        "beam-forming",
        "beamformer",
    ],
    "null_steering": [
        "null steering",
        "null-steering",
        "null placement",
    ],
    "active_noise_cancellation": [
        "active noise cancellation",
        "active noise control",
        "anc ",
    ],
    "crosstalk_cancellation": [
        "crosstalk cancellation",
        "cross-talk cancellation",
        "xtc",
    ],
    "adaptive_filtering": [
        "adaptive filter",
        "adaptive filtering",
        "lms algorithm",
        "nlms algorithm",
        "rls algorithm",
    ],
}

METRIC_NAMES: dict[str, list[str]] = {
    "acoustic_contrast_db": [
        "acoustic contrast",
        "contrast ratio",
    ],
    "dark_zone_attenuation": [
        "dark zone attenuation",
        "dark zone",
        "dark-zone",
        "quiet zone",
    ],
    "bright_zone_error": [
        "bright zone error",
        "bright zone distortion",
        "reproduction error",
    ],
    "speech_privacy": [
        "speech privacy",
        "speech intelligibility",
        "sii ",
        "speech transmission index",
    ],
    "latency_ms": [
        "latency",
        "processing delay",
        "algorithmic delay",
    ],
    "spl_error": [
        "sound pressure level error",
        "spl error",
        "pressure error",
    ],
    "array_effort": [
        "array effort",
        "control effort",
        "loudspeaker effort",
    ],
}

HARDWARE_TERMS: dict[str, list[str]] = {
    "loudspeaker_array": [
        "loudspeaker array",
        "speaker array",
        "loudspeaker arrangement",
    ],
    "soundbar": [
        "soundbar",
        "sound bar",
    ],
    "headphone": [
        "headphone",
        "headphones",
        "earphone",
    ],
    "headrest": [
        "headrest",
        "head rest",
        "headrest speaker",
    ],
    "microphone_array": [
        "microphone array",
        "mic array",
        "microphone arrangement",
    ],
    "dsp_platform": [
        "dsp ",
        "fpga",
        "gpu acceleration",
        "real-time processor",
    ],
}

FAILURE_MODES: dict[str, list[str]] = {
    "head_movement": [
        "head movement",
        "head tracking",
        "listener movement",
        "position change",
    ],
    "room_reverberation": [
        "reverberation",
        "room acoustics",
        "reflections",
        "reverberant",
    ],
    "low_frequency_leakage": [
        "low frequency leakage",
        "low-frequency",
        "bass leakage",
    ],
    "calibration_drift": [
        "calibration drift",
        "recalibration",
        "calibration error",
    ],
    "robustness": [
        "robustness",
        "sensitivity",
        "ill-conditioned",
        "regularization",
    ],
}

RELATED_METHODS: dict[str, list[str]] = {
    "acoustic_contrast_control": ["pressure_matching", "beamforming"],
    "pressure_matching": ["acoustic_contrast_control", "beamforming"],
    "beamforming": ["acoustic_contrast_control", "null_steering"],
    "null_steering": ["beamforming", "acoustic_contrast_control"],
    "active_noise_cancellation": ["adaptive_filtering", "crosstalk_cancellation"],
    "crosstalk_cancellation": ["active_noise_cancellation", "beamforming"],
    "adaptive_filtering": ["active_noise_cancellation", "beamforming"],
}

# The method_family vocabulary declared by the repro experiment runner. repro's
# recommend-method boosts a runnable reproduction only when the proposal's
# method_family EXACTLY matches one of a reproduction's declared families, so
# co-scientist's induced taxonomy must speak this vocabulary at the runner
# boundary. Small and stable; refreshable by walking repro's metrics-surface.
REPRO_ANCHOR_FAMILIES: tuple[str, ...] = (
    "acoustic_contrast_control",
    "pressure_matching",
    "sound_zone_control",
    "robust_pressure_matching",
    "variable_span_tradeoff",
    "parametric_array_modeling",
    "sound_field_estimation",
    "sound_field_reconstruction",
    "physics_informed_neural_network",
    "kernel_interpolation",
    "adaptive_kernel_interpolation",
    "boundary_integral",
)

# co-scientist induced-family canonical names (snake_case) → repro anchor family.
# Collapses cross-system drift and internal near-duplicates deterministically.
FAMILY_ALIASES: dict[str, str] = {
    "personal_sound_zone_control": "sound_zone_control",
    "personal_sound_zones_system_design": "sound_zone_control",
    "sound_zone": "sound_zone_control",
    "variable_span_trade_off_filter": "variable_span_tradeoff",
    "variable_span_tradeoff_filter": "variable_span_tradeoff",
    "parametric_array_loudspeaker": "parametric_array_modeling",
    "parametric_loudspeaker_sound_zones": "parametric_array_modeling",
}

_CANON_RE = re.compile(r"[^a-z0-9]+")


def canonicalize_name(name: str) -> str:
    """snake_case a free-form family name (lowercase, non-alphanumerics → '_')."""
    return _CANON_RE.sub("_", name.strip().lower()).strip("_")


def canonicalize_family(name: str) -> str:
    """Canonicalize a method-family name and collapse it onto a repro anchor.

    snake_case first, then apply FAMILY_ALIASES so co-scientist synonyms and
    near-duplicates resolve to the vocabulary repro's runner exact-matches.
    """
    canon = canonicalize_name(name)
    return FAMILY_ALIASES.get(canon, canon)


# Reverse index of METRIC_NAMES: snake_cased synonym → canonical metric name.
# Canonical keys are added last so a canonical name always maps to itself even if
# a synonym of another metric happened to collide.
_METRIC_SYNONYM_INDEX: dict[str, str] = {}
for _canonical, _synonyms in METRIC_NAMES.items():
    for _syn in _synonyms:
        _METRIC_SYNONYM_INDEX[canonicalize_name(_syn)] = _canonical
for _canonical in METRIC_NAMES:
    _METRIC_SYNONYM_INDEX[_canonical] = _canonical
del _canonical, _synonyms, _syn


def canonicalize_metric(name: str) -> str:
    """Canonicalize a metric name onto the controlled METRIC_NAMES vocabulary.

    snake_case first, then map known synonyms/near-names onto their canonical key
    (e.g. ``acoustic_contrast`` → ``acoustic_contrast_db``) so a card's metric and
    pass-condition names reconcile with the canonical names the runner emits.
    Metrics absent from the vocabulary pass through snake_cased (unrunnable/extra).
    """
    canon = canonicalize_name(name)
    return _METRIC_SYNONYM_INDEX.get(canon, canon)


def classify_text(
    text: str,
    terms: list[OntologyTerm] | None = None,
) -> dict[str, list[str]]:
    lower = text.lower()

    if terms is not None:
        result: dict[str, list[str]] = {}
        for field in _CATEGORY_TO_FIELD.values():
            result[field] = []
        for term in terms:
            kw_list = json.loads(term.keywords)
            if any(kw in lower for kw in kw_list):
                field_name = _CATEGORY_TO_FIELD.get(term.category)
                if field_name and field_name in result:
                    result[field_name].append(term.canonical_name)
        return result

    result = {
        "method_families": [],
        "metrics": [],
        "hardware": [],
        "failure_modes": [],
    }
    for canonical, keywords in METHOD_FAMILIES.items():
        if any(kw in lower for kw in keywords):
            result["method_families"].append(canonical)
    for canonical, keywords in METRIC_NAMES.items():
        if any(kw in lower for kw in keywords):
            result["metrics"].append(canonical)
    for canonical, keywords in HARDWARE_TERMS.items():
        if any(kw in lower for kw in keywords):
            result["hardware"].append(canonical)
    for canonical, keywords in FAILURE_MODES.items():
        if any(kw in lower for kw in keywords):
            result["failure_modes"].append(canonical)
    return result


def get_related_methods(
    terms: list[OntologyTerm],
    relationships: list[OntologyRelationship],
) -> dict[str, list[str]]:
    id_to_name = {t.id: t.canonical_name for t in terms}
    method_terms = {t.id for t in terms if t.category == "method"}
    related: dict[str, list[str]] = {}
    for rel in relationships:
        if rel.source_term_id in method_terms and rel.target_term_id in method_terms:
            src = id_to_name[rel.source_term_id]
            tgt = id_to_name[rel.target_term_id]
            related.setdefault(src, []).append(tgt)
            related.setdefault(tgt, []).append(src)
    return related
