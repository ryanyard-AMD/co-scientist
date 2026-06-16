import json
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from coscientist.config import settings
from coscientist.database import Base
from coscientist.schemas.goal import (
    DeviceConstraints,
    GoalCreate,
    GoalStatusEnum,
    GoalUpdate,
    SuccessCriterion,
)
from coscientist.schemas.scout import ScoutRunRequest
from coscientist.services import goal as svc
from coscientist.services import scout as scout_svc

app = typer.Typer(no_args_is_help=True)
goal_app = typer.Typer(no_args_is_help=True, help="Manage research goals")
scout_app = typer.Typer(no_args_is_help=True, help="Scout evidence for research goals")
app.add_typer(goal_app, name="goal")
app.add_typer(scout_app, name="scout")

console = Console()


def _get_session():
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


@goal_app.command("create")
def goal_create(
    name: str = typer.Option(..., "--name", "-n", help="Goal name"),
    app_target: str = typer.Option(..., "--app", "-a", help="Target application"),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    criteria: Optional[str] = typer.Option(
        None, "--criteria", help="JSON list of success criteria"
    ),
    constraints: Optional[str] = typer.Option(
        None, "--constraints", help="JSON object of device constraints"
    ),
):
    """Create a new research goal."""
    parsed_criteria: list[SuccessCriterion] = []
    if criteria:
        for c in json.loads(criteria):
            parsed_criteria.append(SuccessCriterion(**c))

    parsed_constraints: DeviceConstraints | None = None
    if constraints:
        parsed_constraints = DeviceConstraints(**json.loads(constraints))

    data = GoalCreate(
        name=name,
        description=description,
        target_application=app_target,
        success_criteria=parsed_criteria,
        device_constraints=parsed_constraints,
    )
    db = _get_session()
    try:
        result = svc.create(db, data)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@goal_app.command("list")
def goal_list(
    status: Optional[GoalStatusEnum] = typer.Option(None, "--status", "-s"),
):
    """List research goals."""
    db = _get_session()
    try:
        items, total = svc.list_goals(db, status=status)
        table = Table(title=f"Research Goals ({total} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Application")
        table.add_column("Status", style="green")
        for g in items:
            table.add_row(g.id[:8] + "…", g.name, g.target_application, g.status.value)
        console.print(table)
    finally:
        db.close()


@goal_app.command("show")
def goal_show(goal_id: str = typer.Argument(...)):
    """Show full details of a research goal."""
    db = _get_session()
    try:
        result = svc.get(db, goal_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@goal_app.command("activate")
def goal_activate(goal_id: str = typer.Argument(...)):
    """Transition a draft goal to active."""
    db = _get_session()
    try:
        result = svc.transition(db, goal_id, GoalStatusEnum.active)
        console.print(f"[green]Goal {goal_id[:8]}… is now {result.status.value}[/green]")
    finally:
        db.close()


@goal_app.command("archive")
def goal_archive(goal_id: str = typer.Argument(...)):
    """Archive a goal."""
    db = _get_session()
    try:
        result = svc.transition(db, goal_id, GoalStatusEnum.archived)
        console.print(f"[yellow]Goal {goal_id[:8]}… archived[/yellow]")
    finally:
        db.close()


@goal_app.command("delete")
def goal_delete(
    goal_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a draft goal."""
    if not yes:
        typer.confirm(f"Delete goal {goal_id}?", abort=True)
    db = _get_session()
    try:
        svc.delete(db, goal_id)
        console.print(f"[red]Goal {goal_id[:8]}… deleted[/red]")
    finally:
        db.close()


# --- Scout commands ---


@scout_app.command("run")
def scout_run(
    goal_id: str = typer.Argument(...),
    method: Optional[str] = typer.Option(None, "--method", "-m", help="Filter by method family"),
    top_k: int = typer.Option(20, "--top-k", "-k"),
):
    """Run scout evidence retrieval for a goal."""
    db = _get_session()
    try:
        request = ScoutRunRequest(
            method_families=[method] if method else None,
            top_k=top_k,
        )
        result = scout_svc.run_scout(db, goal_id, request)
        console.print(f"[green]Scout run {result.scout_run_id[:8]}… complete[/green]")
        console.print(f"  Evidence records: {result.summary.total_evidence}")
        console.print(f"  Papers found: {result.summary.total_papers}")
        console.print(f"  Methods found: {', '.join(result.summary.method_families_found) or 'none'}")
        console.print(
            f"  Strong: {result.summary.strong_evidence_count}, "
            f"Weak: {result.summary.weak_evidence_count}"
        )
        if result.summary.warnings:
            console.print(f"[yellow]  Warnings: {len(result.summary.warnings)}[/yellow]")
            for w in result.summary.warnings:
                console.print(
                    f"    - {w.query_or_category}: "
                    f"{w.evidence_strength.value} ({w.papers_found} papers)"
                )
    finally:
        db.close()


@scout_app.command("evidence")
def scout_evidence(
    goal_id: str = typer.Argument(...),
    group_by: Optional[str] = typer.Option(
        None, "--group-by", "-g",
        help="Group by: method|metric|hardware|failure_mode",
    ),
):
    """List evidence for a goal, optionally grouped."""
    db = _get_session()
    try:
        if group_by:
            group_key = {
                "method": "method_family",
                "metric": "metric",
                "hardware": "hardware",
                "failure_mode": "failure_mode",
            }.get(group_by, group_by)
            groups = scout_svc.get_evidence_groups(db, goal_id, group_by=group_key)
            table = Table(
                title=f"Evidence Groups ({groups.total_groups} groups, "
                      f"{groups.total_evidence} records)"
            )
            table.add_column("Group", style="cyan")
            table.add_column("Type")
            table.add_column("Count", justify="right")
            table.add_column("Papers", justify="right")
            table.add_column("Strength", style="green")
            table.add_column("Avg Score", justify="right")
            for g in groups.groups:
                table.add_row(
                    g.group_key, g.group_type,
                    str(g.count), str(g.paper_count),
                    g.evidence_strength.value, f"{g.avg_score:.3f}",
                )
            console.print(table)
        else:
            items, total = scout_svc.get_evidence(db, goal_id)
            table = Table(title=f"Evidence Records ({total} total)")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Paper", max_width=30)
            table.add_column("Section")
            table.add_column("Score", justify="right")
            table.add_column("Methods")
            table.add_column("Strength")
            for item in items:
                methods = ", ".join(item.method_families[:2])
                table.add_row(
                    item.id[:8] + "…",
                    item.title[:30],
                    item.section_title or "-",
                    f"{item.score:.3f}",
                    methods or "-",
                    item.evidence_strength.value,
                )
            console.print(table)
    finally:
        db.close()


@scout_app.command("summary")
def scout_summary(goal_id: str = typer.Argument(...)):
    """Show scout summary with warnings."""
    db = _get_session()
    try:
        summary = scout_svc.get_summary(db, goal_id)
        console.print_json(summary.model_dump_json(indent=2))
    finally:
        db.close()
