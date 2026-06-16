"""
PSZ domain keyword dictionaries for evidence classification.
Falls back to hardcoded dicts when no DB terms are provided.
"""

from __future__ import annotations

import json
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
