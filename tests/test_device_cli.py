from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from coscientist.cli.app import _parse_sweep, app
from coscientist.schemas.device import (
    DeviceOptimizeCandidate,
    DeviceOptimizeResult,
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


def test_device_optimize_requires_sweep():
    result = runner.invoke(app, ["device", "optimize", "dev-1", "goal-1"])
    assert result.exit_code == 1
