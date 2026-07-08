"""Phase 4: cross-paper comparison passthrough + CLI rendering."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from typer.testing import CliRunner

from coscientist.cli.app import app
from coscientist.clients.retrieval import ComparePaper, PaperComparison
from coscientist.services import scout as scout_svc
from conftest import MockRetrievalClient

runner = CliRunner()


def test_compare_service_passthrough():
    result = scout_svc.compare_papers(
        ["paper_a", "paper_b"],
        dimensions=["methods", "results"],
        retrieval_client=MockRetrievalClient(),
    )
    assert {p.paper_id for p in result.papers} == {"paper_a", "paper_b"}
    assert set(result.dimensions) == {"methods", "results"}
    assert result.dimensions["methods"]["paper_a"] == "methods of paper_a"


def test_compare_service_requires_paper_ids():
    with pytest.raises(HTTPException) as exc:
        scout_svc.compare_papers([], retrieval_client=MockRetrievalClient())
    assert exc.value.status_code == 422


def test_compare_cli_renders_dimensions():
    canned = PaperComparison(
        papers=[ComparePaper(paper_id="pa", title="Alpha Paper"),
                ComparePaper(paper_id="pb", title="Beta Paper")],
        dimensions={"methods": {"pa": "ACC approach", "pb": "pressure matching"}},
        summary="both use optimization",
        chunks_used=7,
    )
    with patch.object(scout_svc, "compare_papers", return_value=canned):
        result = runner.invoke(app, ["scout", "compare", "-p", "pa", "-p", "pb", "-d", "methods"])
    assert result.exit_code == 0, result.output
    assert "Alpha Paper" in result.output
    assert "methods" in result.output
    assert "both use optimization" in result.output


def test_compare_cli_requires_two_papers():
    result = runner.invoke(app, ["scout", "compare", "-p", "only_one"])
    assert result.exit_code == 1
    assert "at least two" in result.output.lower()
