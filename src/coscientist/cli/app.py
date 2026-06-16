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
from coscientist.services import goal as svc

app = typer.Typer(no_args_is_help=True)
goal_app = typer.Typer(no_args_is_help=True, help="Manage research goals")
app.add_typer(goal_app, name="goal")

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
