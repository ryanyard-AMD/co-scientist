"""
PSZ domain keyword dictionaries for evidence classification.
Pre-ONTOLOGY placeholder — will be replaced by graph-based classification.
"""

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


def classify_text(text: str) -> dict[str, list[str]]:
    lower = text.lower()
    result: dict[str, list[str]] = {
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
