"""CLI coverage for the handoff-control commands (CS-APPROVAL-010/011, CS-UI-012):
retry, cancel, resubmit, handoff-requests. The underlying services are tested in
test_phase3_handoff_control.py; these tests verify the CLI wiring and clean
error handling for a not-yet-submitted / unknown experiment.
"""

import pytest
from typer.testing import CliRunner

from coscientist.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def use_in_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("CS_DATABASE_URL", f"sqlite:///{db_path}")
    import importlib
    import coscientist.config as cfg_mod
    import coscientist.cli.app as cli_mod
    importlib.reload(cfg_mod)
    importlib.reload(cli_mod)


def test_cancel_unknown_experiment_errors_cleanly():
    result = runner.invoke(app, ["approval", "cancel", "no-such-exp", "no-such-goal"])
    assert result.exit_code == 1
    assert "Cancel failed" in result.output


def test_resubmit_unknown_experiment_errors_cleanly():
    result = runner.invoke(app, ["approval", "resubmit", "no-such-exp", "no-such-goal"])
    assert result.exit_code == 1
    assert "Resubmit failed" in result.output


def test_retry_unknown_experiment_errors_cleanly():
    result = runner.invoke(app, ["approval", "retry", "no-such-exp", "no-such-goal"])
    assert result.exit_code == 1
    assert "Retry failed" in result.output


def test_handoff_requests_empty_lists_zero():
    result = runner.invoke(app, ["approval", "handoff-requests", "no-such-exp", "no-such-goal"])
    assert result.exit_code == 0
    assert "0 handoff request(s)" in result.output
