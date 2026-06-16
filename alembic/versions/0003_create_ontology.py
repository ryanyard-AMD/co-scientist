"""create ontology_terms and ontology_relationships tables with seed data

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-16
"""

import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


SEED_TERMS: list[dict] = [
    # --- Methods (13) ---
    {"name": "acoustic_contrast_control", "cat": "method", "desc": "Maximizes acoustic energy ratio between bright and dark zones", "kw": ["acoustic contrast control", "acoustic contrast maximization", "acc method"]},
    {"name": "pressure_matching", "cat": "method", "desc": "Minimizes reproduction error in the bright zone", "kw": ["pressure matching", "pressure matching method", "pm method"]},
    {"name": "beamforming", "cat": "method", "desc": "Steers acoustic beams toward target zones", "kw": ["beamforming", "beam forming", "beam-forming", "beamformer"]},
    {"name": "null_steering", "cat": "method", "desc": "Places acoustic nulls at dark-zone positions", "kw": ["null steering", "null-steering", "null placement"]},
    {"name": "crosstalk_cancellation", "cat": "method", "desc": "Cancels unwanted signal leakage between zones", "kw": ["crosstalk cancellation", "cross-talk cancellation", "xtc"]},
    {"name": "active_noise_control", "cat": "method", "desc": "Generates anti-noise to cancel unwanted sound", "kw": ["active noise cancellation", "active noise control", "anc "]},
    {"name": "adaptive_filtering", "cat": "method", "desc": "Online filter adaptation for time-varying conditions", "kw": ["adaptive filter", "adaptive filtering", "lms algorithm", "nlms algorithm", "rls algorithm"]},
    {"name": "modal_control", "cat": "method", "desc": "Controls acoustic modes in enclosed spaces", "kw": ["modal control", "mode control", "room mode"]},
    {"name": "wave_field_synthesis", "cat": "method", "desc": "Reproduces arbitrary sound fields using dense arrays", "kw": ["wave field synthesis", "wfs", "wave-field synthesis"]},
    {"name": "perceptual_weighting", "cat": "method", "desc": "Applies psychoacoustic weighting to optimization", "kw": ["perceptual weighting", "psychoacoustic weighting", "perceptually weighted"]},
    {"name": "head_tracking_compensation", "cat": "method", "desc": "Adjusts sound field based on tracked head position", "kw": ["head tracking compensation", "head tracking", "head-tracking"]},
    {"name": "transfer_function_estimation", "cat": "method", "desc": "Estimates acoustic transfer functions for zone control", "kw": ["transfer function estimation", "transfer function measurement", "atf estimation"]},
    {"name": "room_impulse_response_modeling", "cat": "method", "desc": "Models room acoustics for filter design", "kw": ["room impulse response", "rir modeling", "rir estimation", "room impulse"]},

    # --- Acoustic Goals (11) ---
    {"name": "bright_zone_fidelity", "cat": "acoustic_goal", "desc": "High-quality reproduction in the target listening zone", "kw": ["bright zone fidelity", "bright-zone fidelity", "reproduction quality"]},
    {"name": "dark_zone_attenuation", "cat": "acoustic_goal", "desc": "Minimizing sound leakage into quiet zones", "kw": ["dark zone attenuation", "dark-zone attenuation", "quiet zone"]},
    {"name": "acoustic_contrast", "cat": "acoustic_goal", "desc": "Maximizing energy difference between bright and dark zones", "kw": ["acoustic contrast", "contrast ratio", "zone contrast"]},
    {"name": "speech_privacy", "cat": "acoustic_goal", "desc": "Preventing speech intelligibility outside target zone", "kw": ["speech privacy", "speech confidentiality", "private listening"]},
    {"name": "listener_intelligibility", "cat": "acoustic_goal", "desc": "Maintaining speech clarity for the target listener", "kw": ["listener intelligibility", "speech intelligibility", "speech clarity"]},
    {"name": "low_leakage_music_playback", "cat": "acoustic_goal", "desc": "Music playback with minimal leakage to other zones", "kw": ["low leakage", "music leakage", "music isolation"]},
    {"name": "multi_listener_isolation", "cat": "acoustic_goal", "desc": "Independent audio for multiple simultaneous listeners", "kw": ["multi listener", "multi-listener", "multiple listener", "independent zones"]},
    {"name": "robustness_to_movement", "cat": "acoustic_goal", "desc": "Maintaining performance under listener movement", "kw": ["robustness to movement", "movement robustness", "position robustness"]},
    {"name": "low_latency_playback", "cat": "acoustic_goal", "desc": "Minimal processing delay for real-time applications", "kw": ["low latency", "real-time", "real time", "low delay"]},
    {"name": "low_calibration_burden", "cat": "acoustic_goal", "desc": "Minimizing setup and calibration effort", "kw": ["low calibration", "calibration burden", "calibration-free", "minimal calibration"]},
    {"name": "spatial_fidelity", "cat": "acoustic_goal", "desc": "Accurate spatial reproduction of the sound scene", "kw": ["spatial fidelity", "spatial accuracy", "spatial reproduction"]},

    # --- Metrics (17) ---
    {"name": "acoustic_contrast_db", "cat": "metric", "desc": "Acoustic contrast measured in decibels", "kw": ["acoustic contrast", "contrast ratio"]},
    {"name": "bright_zone_spl_error", "cat": "metric", "desc": "SPL reproduction error in the bright zone", "kw": ["bright zone error", "bright zone distortion", "reproduction error"]},
    {"name": "dark_zone_spl", "cat": "metric", "desc": "Absolute SPL level in the dark zone", "kw": ["dark zone spl", "dark zone level"]},
    {"name": "dark_zone_attenuation_db", "cat": "metric", "desc": "Attenuation achieved in the dark zone in dB", "kw": ["dark zone attenuation", "dark-zone", "quiet zone"]},
    {"name": "speech_transmission_index", "cat": "metric", "desc": "STI measuring speech intelligibility", "kw": ["speech transmission index", "sti ", "sii "]},
    {"name": "speech_privacy_index", "cat": "metric", "desc": "Index quantifying speech privacy level", "kw": ["speech privacy index", "privacy index", "speech privacy"]},
    {"name": "mse_pressure_error", "cat": "metric", "desc": "Mean squared error of pressure reproduction", "kw": ["mse pressure", "pressure error", "mean squared error"]},
    {"name": "frequency_response_error", "cat": "metric", "desc": "Deviation from target frequency response", "kw": ["frequency response error", "frequency response deviation"]},
    {"name": "latency_ms", "cat": "metric", "desc": "Processing latency in milliseconds", "kw": ["latency", "processing delay", "algorithmic delay"]},
    {"name": "compute_load", "cat": "metric", "desc": "Computational resource requirements", "kw": ["compute load", "computational cost", "computational complexity", "flops"]},
    {"name": "calibration_time", "cat": "metric", "desc": "Time required for system calibration", "kw": ["calibration time", "setup time", "calibration duration"]},
    {"name": "robustness_to_position_shift", "cat": "metric", "desc": "Performance degradation with listener displacement", "kw": ["robustness to position", "position shift", "position sensitivity"]},
    {"name": "room_generalization_score", "cat": "metric", "desc": "Performance consistency across different rooms", "kw": ["room generalization", "generalization score", "cross-room"]},
    {"name": "power_consumption", "cat": "metric", "desc": "Electrical power drawn by the system", "kw": ["power consumption", "power draw", "energy consumption"]},
    {"name": "speaker_count", "cat": "metric", "desc": "Number of loudspeakers required", "kw": ["speaker count", "number of speakers", "loudspeaker count"]},
    {"name": "microphone_count", "cat": "metric", "desc": "Number of microphones required", "kw": ["microphone count", "number of microphones", "mic count"]},
    {"name": "array_effort", "cat": "metric", "desc": "Total drive signal energy of the loudspeaker array", "kw": ["array effort", "control effort", "loudspeaker effort"]},

    # --- Hardware (12) ---
    {"name": "speaker_array", "cat": "hardware", "desc": "General loudspeaker array configuration", "kw": ["loudspeaker array", "speaker array", "loudspeaker arrangement"]},
    {"name": "near_field_speaker_array", "cat": "hardware", "desc": "Close-proximity speaker array for personal zones", "kw": ["near field speaker", "near-field speaker", "personal speaker"]},
    {"name": "headrest_speaker_array", "cat": "hardware", "desc": "Speakers embedded in a headrest", "kw": ["headrest", "head rest", "headrest speaker"]},
    {"name": "desktop_soundbar_array", "cat": "hardware", "desc": "Desktop-mounted soundbar speaker array", "kw": ["soundbar", "sound bar", "desktop soundbar"]},
    {"name": "distributed_loudspeakers", "cat": "hardware", "desc": "Spatially distributed loudspeakers", "kw": ["distributed loudspeaker", "distributed speaker"]},
    {"name": "calibration_microphones", "cat": "hardware", "desc": "Microphones used for system calibration", "kw": ["calibration microphone", "measurement microphone"]},
    {"name": "feedback_microphones", "cat": "hardware", "desc": "Microphones for feedback/error sensing", "kw": ["feedback microphone", "error microphone", "monitoring microphone"]},
    {"name": "head_tracking_sensor", "cat": "hardware", "desc": "Sensor for tracking listener head position", "kw": ["head tracking sensor", "head tracker", "position sensor"]},
    {"name": "embedded_dsp", "cat": "hardware", "desc": "Embedded digital signal processor", "kw": ["dsp ", "embedded dsp", "signal processor"]},
    {"name": "gpu_simulation_backend", "cat": "hardware", "desc": "GPU-based computation for simulation", "kw": ["gpu acceleration", "gpu simulation", "gpu backend"]},
    {"name": "amplifier_channel_array", "cat": "hardware", "desc": "Multi-channel amplifier system", "kw": ["amplifier", "amplifier channel", "power amplifier"]},
    {"name": "microphone_array", "cat": "hardware", "desc": "Array of microphones for sensing", "kw": ["microphone array", "mic array", "microphone arrangement"]},

    # --- Failure Modes (5) ---
    {"name": "head_movement", "cat": "failure_mode", "desc": "Performance degradation when listener moves", "kw": ["head movement", "head tracking", "listener movement", "position change"]},
    {"name": "room_reverberation", "cat": "failure_mode", "desc": "Performance degradation due to room reflections", "kw": ["reverberation", "room acoustics", "reflections", "reverberant"]},
    {"name": "low_frequency_leakage", "cat": "failure_mode", "desc": "Inability to control low-frequency sound", "kw": ["low frequency leakage", "low-frequency", "bass leakage"]},
    {"name": "calibration_drift", "cat": "failure_mode", "desc": "Gradual degradation of calibrated performance", "kw": ["calibration drift", "recalibration", "calibration error"]},
    {"name": "robustness", "cat": "failure_mode", "desc": "General sensitivity to parameter variations", "kw": ["robustness", "sensitivity", "ill-conditioned", "regularization"]},

    # --- Scene Assumptions (5) ---
    {"name": "room_geometry", "cat": "scene_assumption", "desc": "Physical dimensions and shape of the room", "kw": ["room geometry", "room dimensions", "room size", "room shape"]},
    {"name": "reverberation_profile", "cat": "scene_assumption", "desc": "Reverberation characteristics of the environment", "kw": ["reverberation profile", "rt60", "reverberation time", "decay time"]},
    {"name": "listener_position", "cat": "scene_assumption", "desc": "Expected position of the target listener", "kw": ["listener position", "listening position", "head position", "receiver position"]},
    {"name": "source_placement", "cat": "scene_assumption", "desc": "Physical placement of sound sources", "kw": ["source placement", "speaker placement", "loudspeaker position", "source position"]},
    {"name": "dark_zone_placement", "cat": "scene_assumption", "desc": "Physical location of quiet/dark zones", "kw": ["dark zone placement", "dark zone position", "quiet zone placement"]},
]

SEED_RELATIONSHIPS: list[tuple[str, str]] = [
    ("acoustic_contrast_control", "pressure_matching"),
    ("acoustic_contrast_control", "beamforming"),
    ("pressure_matching", "beamforming"),
    ("beamforming", "null_steering"),
    ("active_noise_control", "adaptive_filtering"),
    ("active_noise_control", "crosstalk_cancellation"),
    ("crosstalk_cancellation", "beamforming"),
    ("adaptive_filtering", "beamforming"),
]


def upgrade() -> None:
    op.create_table(
        "ontology_terms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("keywords", sa.Text, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint("uq_category_name", "ontology_terms", ["category", "canonical_name"])
    op.create_index("ix_ontology_terms_category", "ontology_terms", ["category"])
    op.create_index("ix_ontology_terms_status", "ontology_terms", ["status"])

    op.create_table(
        "ontology_relationships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_term_id", sa.String(36), nullable=False),
        sa.Column("target_term_id", sa.String(36), nullable=False),
        sa.Column("relationship_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ontology_rel_source", "ontology_relationships", ["source_term_id"])
    op.create_index("ix_ontology_rel_target", "ontology_relationships", ["target_term_id"])

    # Seed terms
    terms_table = sa.table(
        "ontology_terms",
        sa.column("id", sa.String),
        sa.column("canonical_name", sa.String),
        sa.column("category", sa.String),
        sa.column("description", sa.Text),
        sa.column("keywords", sa.Text),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    now = _now()
    name_to_id: dict[str, str] = {}
    rows = []
    for t in SEED_TERMS:
        tid = _uid()
        name_to_id[t["name"]] = tid
        rows.append({
            "id": tid,
            "canonical_name": t["name"],
            "category": t["cat"],
            "description": t["desc"],
            "keywords": json.dumps(t["kw"]),
            "status": "active",
            "created_at": now,
            "updated_at": now,
        })
    op.bulk_insert(terms_table, rows)

    # Seed relationships
    rels_table = sa.table(
        "ontology_relationships",
        sa.column("id", sa.String),
        sa.column("source_term_id", sa.String),
        sa.column("target_term_id", sa.String),
        sa.column("relationship_type", sa.String),
        sa.column("created_at", sa.DateTime),
    )

    rel_rows = []
    for src_name, tgt_name in SEED_RELATIONSHIPS:
        if src_name in name_to_id and tgt_name in name_to_id:
            rel_rows.append({
                "id": _uid(),
                "source_term_id": name_to_id[src_name],
                "target_term_id": name_to_id[tgt_name],
                "relationship_type": "related_to",
                "created_at": now,
            })
    if rel_rows:
        op.bulk_insert(rels_table, rel_rows)


def downgrade() -> None:
    op.drop_index("ix_ontology_rel_target", table_name="ontology_relationships")
    op.drop_index("ix_ontology_rel_source", table_name="ontology_relationships")
    op.drop_table("ontology_relationships")
    op.drop_index("ix_ontology_terms_status", table_name="ontology_terms")
    op.drop_index("ix_ontology_terms_category", table_name="ontology_terms")
    op.drop_unique_constraint("uq_category_name", "ontology_terms")
    op.drop_table("ontology_terms")
