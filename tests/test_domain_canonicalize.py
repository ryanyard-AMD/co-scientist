import pytest

from coscientist.domain import (
    FAMILY_ALIASES,
    METRIC_NAMES,
    REPRO_ANCHOR_FAMILIES,
    canonicalize_family,
    canonicalize_metric,
    canonicalize_name,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Acoustic Contrast Control", "acoustic_contrast_control"),
        ("variable-span tradeoff", "variable_span_tradeoff"),
        ("  Pressure   Matching  ", "pressure_matching"),
        ("PIML/Fig4", "piml_fig4"),
    ],
)
def test_canonicalize_name_snake_cases(raw, expected):
    assert canonicalize_name(raw) == expected


@pytest.mark.parametrize("alias,anchor", list(FAMILY_ALIASES.items()))
def test_canonicalize_family_collapses_aliases(alias, anchor):
    assert canonicalize_family(alias) == anchor
    assert anchor in REPRO_ANCHOR_FAMILIES


@pytest.mark.parametrize("anchor", REPRO_ANCHOR_FAMILIES)
def test_anchors_are_fixed_points(anchor):
    # An anchor must canonicalize to itself so backfill/derive are idempotent.
    assert canonicalize_family(anchor) == anchor


def test_canonicalize_family_passes_through_unknown():
    # A co-scientist family with no repro reproduction stays as-is (unrunnable).
    assert canonicalize_family("Boundary Integral Extras") == "boundary_integral_extras"


def test_canonicalize_family_maps_title_case_alias():
    assert canonicalize_family("Personal Sound Zone Control") == "sound_zone_control"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("acoustic_contrast", "acoustic_contrast_db"),
        ("Acoustic Contrast", "acoustic_contrast_db"),
        ("contrast ratio", "acoustic_contrast_db"),
    ],
)
def test_canonicalize_metric_maps_synonyms_to_canonical(raw, expected):
    assert canonicalize_metric(raw) == expected


@pytest.mark.parametrize("canonical", list(METRIC_NAMES))
def test_canonicalize_metric_canonical_keys_are_fixed_points(canonical):
    assert canonicalize_metric(canonical) == canonical


def test_canonicalize_metric_passes_through_unknown():
    # A goal metric with no METRIC_NAMES entry stays snake_cased (extra/unrunnable).
    assert canonicalize_metric("bright_zone_thd") == "bright_zone_thd"
    assert canonicalize_metric("Localization Accuracy") == "localization_accuracy"
