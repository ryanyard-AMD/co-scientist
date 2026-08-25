from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from coscientist.cli.app import _parse_reproduction_sweep, _parse_sweep, app
from coscientist.schemas.device import (
    DeviceOptimizeCandidate,
    DeviceOptimizeResult,
    DeviceReproductionResult,
    DeviceReproductionSweepCandidate,
    DeviceReproductionSweepResult,
    ReproductionPerBand,
    SimulationPerBand,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def use_in_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("CS_DATABASE_URL", f"sqlite:///{db_path}")
    import importlib

    import coscientist.config as cfg_mod

    importlib.reload(cfg_mod)


def test_parse_sweep_coerces_values():
    out = _parse_sweep(["n_elements=4,8,16", "aperture=0.008,0.01", "pal_model=true,false"])
    assert out["n_elements"] == [4, 8, 16]
    assert out["aperture"] == [0.008, 0.01]
    assert out["pal_model"] == [True, False]


def test_parse_sweep_requires_equals():
    with pytest.raises(Exception):
        _parse_sweep(["n_elements"])


def test_parse_reproduction_sweep_supports_vector_candidates():
    out = _parse_reproduction_sweep([
        "n_elements=8,16",
        "listener=0,0.5,0:0,1.0,0",
        "t60=0,0.4",
    ])
    assert out["n_elements"] == [8, 16]
    assert out["listener"] == [[0.0, 0.5, 0.0], [0.0, 1.0, 0.0]]
    assert out["t60"] == [0, 0.4]


def _fake_result():
    return DeviceOptimizeResult(
        device_id="dev-1",
        simulated_at=datetime.now(timezone.utc),
        best_contrast_db=35.77,
        best_overrides={"n_elements": 16},
        target_contrast_db=15.0,
        meets_target=True,
        swept_keys=["n_elements"],
        n_candidates=3,
        rooms_built=3,
        candidates=[
            DeviceOptimizeCandidate(
                overrides={"n_elements": 16}, acoustic_contrast_db=35.77, n_elements=16,
                per_band=[SimulationPerBand(freq_hz=2000.0, contrast_db=38.0)],
            ),
            DeviceOptimizeCandidate(
                overrides={"n_elements": 8}, acoustic_contrast_db=28.33, n_elements=8,
            ),
        ],
        resolved_geometry={"layout": "ula", "n_elements": 16},
        model_flags={"pal_model": "berktay"},
        repro_endpoint="http://localhost:8003/api/v1/device-sim/optimize",
        previous_contrast_db=28.33,
    )


def _fake_reproduction_result():
    return DeviceReproductionResult(
        device_id="dev-1",
        simulated_at=datetime.now(timezone.utc),
        solver="pressure_matching",
        target={"kind": "plane_wave"},
        normalized_reproduction_error=0.2175,
        spatial_correlation=0.9412,
        mean_spl_error_db=1.88,
        max_spl_error_db=4.73,
        array_effort=2.41,
        acoustic_contrast_db=18.6,
        per_band=[
            ReproductionPerBand(
                freq_hz=2000.0,
                normalized_reproduction_error=0.2,
                spatial_correlation=0.95,
                mean_spl_error_db=1.5,
                max_spl_error_db=3.9,
                array_effort=2.1,
                acoustic_contrast_db=20.0,
            )
        ],
        resolved_geometry={"layout": "ula", "n_elements": 16, "control_points": 27, "evaluation_points": 27},
        model_flags={"pal_model": "point_source"},
        repro_endpoint="http://localhost:8003/api/v1/device-sim/reproduce",
        previous_normalized_reproduction_error=0.3,
    )


def _fake_reproduction_sweep_result():
    return DeviceReproductionSweepResult(
        device_id="dev-1",
        simulated_at=datetime.now(timezone.utc),
        solver="pressure_matching",
        target={"kind": "spherical_wave"},
        best_overrides={"n_elements": 16, "listener": [0.0, 1.0, 0.0]},
        normalized_reproduction_error=0.11,
        spatial_correlation=0.98,
        mean_spl_error_db=1.2,
        max_spl_error_db=3.4,
        array_effort=7.8,
        acoustic_contrast_db=5.6,
        swept_keys=["n_elements", "listener"],
        n_candidates=2,
        candidates=[
            DeviceReproductionSweepCandidate(
                overrides={"n_elements": 16, "listener": [0.0, 1.0, 0.0]},
                normalized_reproduction_error=0.11,
                spatial_correlation=0.98,
                mean_spl_error_db=1.2,
                max_spl_error_db=3.4,
                array_effort=7.8,
                acoustic_contrast_db=5.6,
            ),
            DeviceReproductionSweepCandidate(
                overrides={"n_elements": 8, "listener": [0.0, 0.5, 0.0]},
                normalized_reproduction_error=0.22,
                spatial_correlation=0.94,
                mean_spl_error_db=2.3,
                max_spl_error_db=5.6,
                array_effort=3.2,
                acoustic_contrast_db=2.1,
            ),
        ],
        resolved_geometry={"layout": "cap", "n_elements": 16},
        model_flags={"pal_model": "berktay"},
        repro_endpoint="http://localhost:8003/api/v1/device-sim/reproduce",
        previous_normalized_reproduction_error=0.2,
    )


def test_device_optimize_renders_ranked_table():
    with patch("coscientist.services.device.optimize", return_value=_fake_result()) as m:
        result = runner.invoke(
            app, ["device", "optimize", "dev-1", "goal-1", "--sweep", "n_elements=8,16"]
        )
    assert result.exit_code == 0, result.output
    assert "35.77" in result.output
    assert "meets" in result.output
    assert "▲ +7.44 dB" in result.output
    # search space forwarded to the service
    _, _, _, search_space = m.call_args.args
    assert search_space == {"n_elements": [8, 16]}


def test_device_reproduce_renders_quality_metrics():
    with patch("coscientist.services.device.reproduce", return_value=_fake_reproduction_result()) as m:
        result = runner.invoke(
            app,
            [
                "device", "reproduce", "dev-1", "goal-1",
                "--target", "plane_wave",
                "--target-direction", "0,1,0",
                "--set", "n_elements=16",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "Normalized reproduction error" in result.output
    assert "0.2175" in result.output
    assert "Spatial correlation" in result.output
    assert "▼ -0.0825" in result.output
    assert m.call_args.kwargs["target_kind"] == "plane_wave"
    assert m.call_args.kwargs["target_direction"] == [0.0, 1.0, 0.0]
    assert m.call_args.kwargs["overrides"] == {"n_elements": 16}


def test_device_reproduce_sweep_renders_ranked_candidates():
    with patch(
        "coscientist.services.device.reproduce_sweep",
        return_value=_fake_reproduction_sweep_result(),
    ) as m:
        result = runner.invoke(
            app,
            [
                "device", "reproduce-sweep", "dev-1", "goal-1",
                "--sweep", "n_elements=8,16",
                "--sweep", "listener=0,0.5,0:0,1.0,0",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "Ranked reproduction candidates" in result.output
    assert "0.1100" in result.output
    assert "Best reproduction error" in result.output
    assert "▼ -0.0900" in result.output
    _, _, _, search_space = m.call_args.args
    assert search_space == {
        "n_elements": [8, 16],
        "listener": [[0.0, 0.5, 0.0], [0.0, 1.0, 0.0]],
    }


def test_device_optimize_requires_sweep():
    result = runner.invoke(app, ["device", "optimize", "dev-1", "goal-1"])
    assert result.exit_code == 1


def test_device_optimize_regenerates_roadmap_when_flagged():
    from coscientist.schemas.roadmap import (
        ResearchRoadmapItemResponse,
        ResearchRoadmapListResponse,
        RoadmapLaneEnum,
        RoadmapStatusEnum,
    )

    now = datetime.now(timezone.utc)
    rm = ResearchRoadmapListResponse(
        items=[
            ResearchRoadmapItemResponse(
                id="rm-1", workspace_id="goal-1", title="Prototype 16-element cap array",
                description="", lane=RoadmapLaneEnum.device_prototype,
                status=RoadmapStatusEnum.open, priority_score=0.9, priority_rank=1,
                rationale="", estimated_cost="medium", estimated_information_gain="high",
                source_approach_ids=[], source_experiment_id=None, source_device_id="dev-1",
                generation_run_id="run-1", model_used="m", created_at=now, updated_at=now,
            )
        ],
        total=1,
        generation_run_id="run-1234",
    )
    with patch("coscientist.services.device.optimize", return_value=_fake_result()), \
            patch("coscientist.services.roadmap.generate", return_value=rm) as rg:
        result = runner.invoke(
            app,
            ["device", "optimize", "dev-1", "goal-1",
             "--sweep", "n_elements=8,16", "--roadmap"],
        )
    assert result.exit_code == 0, result.output
    rg.assert_called_once()
    assert "Regenerating roadmap" in result.output
    assert "Prototype 16-element cap array" in result.output


def test_device_optimize_skips_roadmap_by_default():
    with patch("coscientist.services.device.optimize", return_value=_fake_result()), \
            patch("coscientist.services.roadmap.generate") as rg:
        result = runner.invoke(
            app, ["device", "optimize", "dev-1", "goal-1", "--sweep", "n_elements=8,16"]
        )
    assert result.exit_code == 0, result.output
    rg.assert_not_called()
