import json
import os

import pytest
from typer.testing import CliRunner

from coscientist.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def use_in_memory_db(tmp_path, monkeypatch):
    """Point the CLI at a temp SQLite DB so tests are isolated."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("CS_DATABASE_URL", f"sqlite:///{db_path}")
    # Re-import settings after env change
    import importlib
    import coscientist.config as cfg_mod
    import coscientist.cli.app as cli_mod
    importlib.reload(cfg_mod)
    importlib.reload(cli_mod)


def test_goal_create_succeeds():
    result = runner.invoke(
        app,
        [
            "goal", "create",
            "--name", "PSZ Test",
            "--app", "personal_sound_zones",
        ],
    )
    assert result.exit_code == 0, result.output


def test_goal_list_empty():
    result = runner.invoke(app, ["goal", "list"])
    assert result.exit_code == 0
    assert "0 total" in result.output


def test_goal_list_after_create():
    runner.invoke(
        app,
        ["goal", "create", "--name", "PSZ A", "--app", "personal_sound_zones"],
    )
    result = runner.invoke(app, ["goal", "list"])
    assert result.exit_code == 0
    assert "1 total" in result.output
    assert "PSZ A" in result.output


def test_goal_create_with_criteria():
    criteria = json.dumps([{"name": "contrast", "operator": ">=", "target": 20.0, "unit": "dB"}])
    result = runner.invoke(
        app,
        [
            "goal", "create",
            "--name", "PSZ With Criteria",
            "--app", "personal_sound_zones",
            "--criteria", criteria,
        ],
    )
    assert result.exit_code == 0, result.output
