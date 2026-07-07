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
from coscientist.schemas.approach import (
    ApproachGenerateRequest,
    ApproachMergeRequest,
    ApproachStatusEnum,
)
from coscientist.schemas.hypothesis import (
    HypothesisGenerateRequest,
    HypothesisStatusEnum,
    HypothesisTypeEnum,
)
from coscientist.schemas.experiment import (
    ExperimentGenerateRequest,
    ExperimentStatusEnum,
    ExperimentTypeEnum,
)
from coscientist.schemas.device import (
    DeviceConceptGenerateRequest,
    DeviceConceptStatusEnum,
    DeviceConceptTransitionRequest,
)
from coscientist.schemas.roadmap import (
    RoadmapLaneEnum,
    RoadmapStatusEnum,
    RoadmapTransitionRequest,
)
from coscientist.schemas.score import WeightProfileEnum
from coscientist.schemas.ontology import OntologyCategoryEnum, TermCreate, TermMergeRequest
from coscientist.schemas.scout import ScoutRunRequest
from coscientist.schemas.critic import ApproachCritiqueRequest
from coscientist.schemas.feedback import FeedbackCreate, FeedbackTargetEnum
from coscientist.services import approval as approval_svc
from coscientist.services import validation as validation_svc
from coscientist.services import device as device_svc
from coscientist.services import evaluation as evaluation_svc
from coscientist.services import feedback as feedback_svc
from coscientist.services import governance as governance_svc
from coscientist.services import roadmap as roadmap_svc
from coscientist.services import runner as runner_svc
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as svc
from coscientist.services import hypothesis as hypothesis_svc
from coscientist.services import ontology as ontology_svc
from coscientist.services import score as score_svc
from coscientist.services import scout as scout_svc
from coscientist.services import critic as critic_svc

app = typer.Typer(no_args_is_help=True)
goal_app = typer.Typer(no_args_is_help=True, help="Manage research goals")
scout_app = typer.Typer(no_args_is_help=True, help="Scout evidence for research goals")
ontology_app = typer.Typer(no_args_is_help=True, help="Manage ontology terms")
approach_app = typer.Typer(no_args_is_help=True, help="Manage approach cards")
critic_app = typer.Typer(no_args_is_help=True, help="Critique approach cards before scoring")
score_app = typer.Typer(no_args_is_help=True, help="Score and compare approach cards")
hypothesis_app = typer.Typer(no_args_is_help=True, help="Manage hypothesis cards")
experiment_app = typer.Typer(no_args_is_help=True, help="Manage experiment cards")
approval_app = typer.Typer(no_args_is_help=True, help="Approve, reject, or request edits on experiments")
validation_app = typer.Typer(no_args_is_help=True, help="Submit experiment results and view validation outcomes")
device_app = typer.Typer(no_args_is_help=True, help="Generate and review candidate device concepts")
roadmap_app = typer.Typer(no_args_is_help=True, help="Generate and manage the research roadmap")
logs_app = typer.Typer(no_args_is_help=True, help="View agent action audit logs")
eval_app = typer.Typer(no_args_is_help=True, help="Evaluation and quality metrics")
feedback_app = typer.Typer(no_args_is_help=True, help="Capture and view feedback on generated artifacts")
app.add_typer(goal_app, name="goal")
app.add_typer(scout_app, name="scout")
app.add_typer(ontology_app, name="ontology")
app.add_typer(approach_app, name="approach")
app.add_typer(critic_app, name="critic")
app.add_typer(score_app, name="score")
app.add_typer(hypothesis_app, name="hypothesis")
app.add_typer(experiment_app, name="experiment")
app.add_typer(approval_app, name="approval")
app.add_typer(validation_app, name="validation")
app.add_typer(device_app, name="device")
app.add_typer(roadmap_app, name="roadmap")
app.add_typer(logs_app, name="logs")
app.add_typer(eval_app, name="eval")
app.add_typer(feedback_app, name="feedback")

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
            table.add_row(g.id, g.name, g.target_application, g.status.value)
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
    synthesize: bool = typer.Option(
        False, "--synthesize", help="Run Claude synthesis per method family"
    ),
):
    """Run scout evidence retrieval for a goal."""
    db = _get_session()
    try:
        request = ScoutRunRequest(
            method_families=[method] if method else None,
            top_k=top_k,
            synthesize=synthesize,
        )
        result = scout_svc.run_scout(db, goal_id, request)
        console.print(f"[green]Scout run {result.scout_run_id[:8]}… complete[/green]")
        console.print(f"  Evidence records: {result.summary.total_evidence}")
        console.print(f"  Papers found: {result.summary.total_papers}")
        console.print(f"  Methods found: {', '.join(result.summary.method_families_found) or 'none'}")
        if result.syntheses:
            console.print(f"  Syntheses: {len(result.syntheses)} method families synthesized")
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
                    item.id,
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


@scout_app.command("synthesis")
def scout_synthesis(
    goal_id: str = typer.Argument(...),
    method: Optional[str] = typer.Option(None, "--method", "-m", help="Filter by method family"),
    scout_run_id: Optional[str] = typer.Option(None, "--scout-run", "-s"),
):
    """Show Claude-generated evidence syntheses for a goal."""
    db = _get_session()
    try:
        syntheses = scout_svc.get_syntheses(
            db, goal_id, scout_run_id=scout_run_id, method_family=method
        )
        if not syntheses:
            console.print("[yellow]No syntheses found. Run `scout run --synthesize` first.[/yellow]")
            return
        for s in syntheses:
            console.print(
                f"\n[bold cyan]{s.method_family}[/bold cyan] "
                f"({s.evidence_count} records, {s.paper_count} papers, "
                f"{len(s.cited_evidence_ids)} citations)"
            )
            console.print(s.synthesis_text)
            if s.key_findings:
                console.print("[bold]Key findings:[/bold]")
                for f in s.key_findings:
                    console.print(f"  - {f}")
            if s.open_questions:
                console.print("[bold]Open questions:[/bold]")
                for q in s.open_questions:
                    console.print(f"  - {q}")
    finally:
        db.close()


# --- Ontology commands ---


@ontology_app.command("seed")
def ontology_seed():
    """Seed default ontology terms and method relationships from the domain dictionaries."""
    db = _get_session()
    try:
        result = ontology_svc.seed_default_ontology(db)
        console.print(
            f"Seeded ontology: {result['terms_added']} terms, "
            f"{result['relationships_added']} relationships added"
        )
    finally:
        db.close()


@ontology_app.command("list")
def ontology_list(
    category: Optional[OntologyCategoryEnum] = typer.Option(
        None, "--category", "-c", help="Filter by category"
    ),
    status: Optional[str] = typer.Option(None, "--status", "-s"),
):
    """List ontology terms."""
    db = _get_session()
    try:
        items, total = ontology_svc.list_terms(db, category=category, status=status)
        table = Table(title=f"Ontology Terms ({total} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Category")
        table.add_column("Status", style="green")
        table.add_column("Keywords", max_width=40)
        for t in items:
            table.add_row(
                t.id,
                t.canonical_name,
                t.category.value,
                t.status,
                ", ".join(t.keywords[:3]) + ("…" if len(t.keywords) > 3 else ""),
            )
        console.print(table)
    finally:
        db.close()


@ontology_app.command("show")
def ontology_show(term_id: str = typer.Argument(...)):
    """Show full details of an ontology term."""
    db = _get_session()
    try:
        result = ontology_svc.get_term(db, term_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@ontology_app.command("add")
def ontology_add(
    name: str = typer.Option(..., "--name", "-n", help="Canonical name"),
    category: OntologyCategoryEnum = typer.Option(..., "--category", "-c"),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    keywords: Optional[str] = typer.Option(None, "--keywords", "-k", help="JSON list of keywords"),
):
    """Add a new ontology term."""
    kw_list = json.loads(keywords) if keywords else []
    data = TermCreate(
        canonical_name=name,
        category=category,
        description=description,
        keywords=kw_list,
    )
    db = _get_session()
    try:
        result = ontology_svc.create_term(db, data)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@ontology_app.command("merge")
def ontology_merge(
    source: str = typer.Option(..., "--source", help="Source term ID (will be deprecated)"),
    target: str = typer.Option(..., "--target", help="Target term ID (will absorb source)"),
):
    """Merge source term into target term."""
    db = _get_session()
    try:
        result = ontology_svc.merge_terms(db, TermMergeRequest(
            source_term_id=source,
            target_term_id=target,
        ))
        console.print(f"[green]Merged into {result.canonical_name} ({result.id[:8]}…)[/green]")
    finally:
        db.close()


# --- Approach commands ---


@approach_app.command("generate")
def approach_generate(
    goal_id: str = typer.Argument(...),
    scout_run_id: Optional[str] = typer.Option(None, "--scout-run", "-s"),
    min_evidence: int = typer.Option(2, "--min-evidence", "-e"),
    method: Optional[str] = typer.Option(None, "--method", "-m", help="Filter by method family"),
):
    """Generate approach cards from evidence."""
    db = _get_session()
    try:
        request = ApproachGenerateRequest(
            scout_run_id=scout_run_id,
            min_evidence_count=min_evidence,
            method_families=[method] if method else None,
        )
        result = approach_svc.generate_approaches(db, goal_id, request)
        console.print(f"[green]Generation run {result.generation_run_id[:8]}… complete[/green]")
        console.print(f"  Approaches created: {result.approaches_created}")
        console.print(f"  Duplicates skipped: {result.approaches_skipped_duplicate}")
        for a in result.approaches:
            console.print(f"  - {a.name} ({a.method_family}) [{a.maturity.value}]")
    finally:
        db.close()


@approach_app.command("list")
def approach_list(
    goal_id: str = typer.Argument(...),
    status: Optional[ApproachStatusEnum] = typer.Option(None, "--status", "-s"),
    method: Optional[str] = typer.Option(None, "--method", "-m"),
):
    """List approach cards for a goal."""
    db = _get_session()
    try:
        items, total = approach_svc.list_approaches(
            db, goal_id, status=status, method_family=method,
        )
        table = Table(title=f"Approach Cards ({total} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Method")
        table.add_column("Status", style="green")
        table.add_column("Maturity")
        table.add_column("Evidence", justify="right")
        for a in items:
            table.add_row(
                a.id,
                a.name,
                a.method_family,
                a.status.value,
                a.maturity.value,
                str(len(a.evidence_links)),
            )
        console.print(table)
    finally:
        db.close()


@approach_app.command("show")
def approach_show(approach_id: str = typer.Argument(...)):
    """Show full details of an approach card."""
    db = _get_session()
    try:
        result = approach_svc.get(db, approach_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@approach_app.command("review")
def approach_review(approach_id: str = typer.Argument(...)):
    """Transition approach card to 'reviewed' status."""
    db = _get_session()
    try:
        result = approach_svc.transition(db, approach_id, ApproachStatusEnum.reviewed)
        console.print(f"[green]Approach {approach_id[:8]}… is now {result.status.value}[/green]")
    finally:
        db.close()


@approach_app.command("merge")
def approach_merge(
    source: str = typer.Option(..., "--source", help="Source approach ID (will be superseded)"),
    target: str = typer.Option(..., "--target", help="Target approach ID (will absorb source)"),
):
    """Merge source approach card into target."""
    db = _get_session()
    try:
        result = approach_svc.merge_approaches(db, ApproachMergeRequest(
            source_approach_id=source,
            target_approach_id=target,
        ))
        console.print(f"[green]Merged into {result.name} ({result.id[:8]}…)[/green]")
    finally:
        db.close()


@approach_app.command("delete")
def approach_delete(
    approach_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a generated approach card."""
    if not yes:
        typer.confirm(f"Delete approach {approach_id}?", abort=True)
    db = _get_session()
    try:
        approach_svc.delete(db, approach_id)
        console.print(f"[red]Approach {approach_id[:8]}… deleted[/red]")
    finally:
        db.close()


# --- Critic commands ---

_VERDICT_STYLE = {"advance": "green", "revise": "yellow", "refute": "red"}


@critic_app.command("run")
def critic_run(
    goal_id: str = typer.Argument(...),
    apply: bool = typer.Option(False, "--apply", help="Apply verdicts (advance→reviewed, refute→refuted)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip --apply confirmation"),
    method: Optional[str] = typer.Option(None, "--method", "-m", help="Filter by method family"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Critique generated approach cards with the LLM critic."""
    if apply and not yes:
        typer.confirm(
            "Apply critic verdicts? This transitions cards (advance→reviewed, refute→refuted).",
            abort=True,
        )
    db = _get_session()
    try:
        request = ApproachCritiqueRequest(
            apply=apply,
            method_families=[method] if method else None,
        )
        result = critic_svc.critique_approaches(db, goal_id, request)
        if as_json:
            console.print_json(result.model_dump_json(indent=2))
            return
        console.print(f"[green]Critique run {result.critique_run_id[:8]}… complete[/green]")
        if result.critiqued_count == 0:
            console.print("[yellow]No generated approach cards to critique.[/yellow]")
            return
        table = Table(title=f"Critiques ({result.critiqued_count} cards)")
        table.add_column("Approach")
        table.add_column("Method")
        table.add_column("Verdict")
        table.add_column("Applied", justify="center")
        table.add_column("Issues", justify="right")
        for c in result.critiques:
            issues = len(c.grounding_issues) + len(c.device_fit_issues) + len(c.maturity_issues)
            style = _VERDICT_STYLE.get(c.verdict.value, "white")
            table.add_row(
                c.approach_name,
                c.method_family,
                f"[{style}]{c.verdict.value}[/{style}]",
                "✓" if c.applied else "-",
                str(issues),
            )
        console.print(table)
        console.print(
            f"  advance: {result.advance_count}, revise: {result.revise_count}, "
            f"refute: {result.refute_count}, applied: {result.applied_count}"
        )
        if not apply and (result.advance_count or result.refute_count):
            console.print("[dim]  Re-run with --apply to act on these verdicts.[/dim]")
    finally:
        db.close()


@critic_app.command("show")
def critic_show(
    goal_id: str = typer.Argument(...),
    approach_id: Optional[str] = typer.Option(None, "--approach", "-a"),
    critique_run_id: Optional[str] = typer.Option(None, "--run", "-r"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Show critic critiques for a goal."""
    db = _get_session()
    try:
        critiques = critic_svc.get_critiques(
            db, goal_id, approach_id=approach_id, critique_run_id=critique_run_id
        )
        if as_json:
            console.print_json(
                json.dumps([c.model_dump(mode="json") for c in critiques], indent=2)
            )
            return
        if not critiques:
            console.print("[yellow]No critiques found. Run `critic run` first.[/yellow]")
            return
        for c in critiques:
            style = _VERDICT_STYLE.get(c.verdict.value, "white")
            console.print(
                f"\n[bold cyan]{c.approach_name}[/bold cyan] ({c.method_family}) "
                f"→ [{style}]{c.verdict.value}[/{style}] "
                f"({len(c.cited_evidence_ids)} citations)"
            )
            console.print(c.summary)
            for label, items in (
                ("Grounding issues", c.grounding_issues),
                ("Device-fit issues", c.device_fit_issues),
                ("Maturity issues", c.maturity_issues),
                ("Strengths", c.strengths),
            ):
                if items:
                    console.print(f"  [bold]{label}:[/bold]")
                    for it in items:
                        console.print(f"    - {it}")
    finally:
        db.close()


# --- Score commands ---


@score_app.command("run")
def score_run(
    goal_id: str = typer.Argument(...),
    profile: WeightProfileEnum = typer.Option(
        WeightProfileEnum.default, "--profile", "-p", help="Weight profile"
    ),
):
    """Score all reviewed/scored approaches for a goal."""
    db = _get_session()
    try:
        results = score_svc.score_all_approaches(db, goal_id, profile)
        console.print(f"[green]Scored {len(results)} approaches with profile '{profile.value}'[/green]")
        for r in results:
            console.print(
                f"  {r.approach_name} ({r.method_family}): "
                f"final={r.final_score:.3f} (total={r.total_score:.3f} - penalty={r.risk_penalty:.3f})"
            )
    finally:
        db.close()


@score_app.command("show")
def score_show(approach_id: str = typer.Argument(...)):
    """Show scores for an approach card."""
    db = _get_session()
    try:
        result = score_svc.get_scores(db, approach_id)
        table = Table(title=f"Scores: {result.approach_name} ({result.method_family})")
        table.add_column("Dimension")
        table.add_column("Score", justify="right")
        table.add_column("Weight", justify="right")
        table.add_column("Weighted", justify="right")
        table.add_column("Low?")
        table.add_column("Rationale", max_width=50)
        for d in result.dimensions:
            table.add_row(
                d.dimension.value,
                f"{d.score:.3f}",
                f"{d.weight:.2f}",
                f"{d.weighted_score:.4f}",
                "!" if d.low_confidence else "",
                d.rationale,
            )
        console.print(table)
        console.print(
            f"Total: {result.total_score:.4f} | "
            f"Risk penalty: {result.risk_penalty:.4f} | "
            f"[bold]Final: {result.final_score:.4f}[/bold]"
        )
    finally:
        db.close()


@score_app.command("compare")
def score_compare(
    goal_id: str = typer.Argument(...),
    profile: WeightProfileEnum = typer.Option(
        WeightProfileEnum.default, "--profile", "-p",
    ),
):
    """Ranked comparison of scored approaches."""
    db = _get_session()
    try:
        result = score_svc.get_comparison(db, goal_id, profile)
        table = Table(title="Approach Comparison (ranked by final score)")
        table.add_column("Rank", justify="right")
        table.add_column("Name")
        table.add_column("Method")
        table.add_column("Final", justify="right", style="bold")
        table.add_column("Total", justify="right")
        table.add_column("Penalty", justify="right")
        for i, a in enumerate(result.approaches, 1):
            table.add_row(
                str(i), a.approach_name, a.method_family,
                f"{a.final_score:.4f}", f"{a.total_score:.4f}", f"{a.risk_penalty:.4f}",
            )
        console.print(table)
    finally:
        db.close()


@score_app.command("pareto")
def score_pareto(goal_id: str = typer.Argument(...)):
    """Show Pareto-optimal approaches."""
    db = _get_session()
    try:
        result = score_svc.get_pareto(db, goal_id)
        console.print(f"[green]Pareto-optimal ({len(result.pareto_optimal)}):[/green]")
        for a in result.pareto_optimal:
            console.print(f"  {a.approach_name} ({a.method_family}) final={a.final_score:.4f}")
        if result.dominated:
            console.print(f"[yellow]Dominated ({len(result.dominated)}):[/yellow]")
            for a in result.dominated:
                console.print(f"  {a.approach_name} ({a.method_family}) final={a.final_score:.4f}")
    finally:
        db.close()


# --- Hypothesis commands ---


@hypothesis_app.command("generate")
def hypothesis_generate(
    goal_id: str = typer.Argument(...),
    max_hypotheses: int = typer.Option(20, "--max", "-m"),
    no_exploratory: bool = typer.Option(False, "--no-exploratory", help="Skip exploratory hypotheses"),
):
    """Generate hypothesis cards from scored approaches."""
    db = _get_session()
    try:
        request = HypothesisGenerateRequest(
            include_exploratory=not no_exploratory,
            max_hypotheses=max_hypotheses,
        )
        result = hypothesis_svc.generate_hypotheses(db, goal_id, request)
        console.print(f"[green]Generation run {result.generation_run_id[:8]}… complete[/green]")
        console.print(f"  Hypotheses created: {result.hypotheses_created}")
        if result.hypotheses_created == 0:
            console.print("[yellow]  No hypotheses generated — need at least 2 scored approaches.[/yellow]")
            console.print("  Run: cs approach list <GOAL_ID> --status scored")
        console.print(f"  Conservative: {result.conservative_count}")
        console.print(f"  Exploratory: {result.exploratory_count}")
        console.print(f"  Duplicates skipped: {result.hypotheses_skipped_duplicate}")
        for h in result.hypotheses:
            conflict = " [CONFLICTS]" if h.has_conflicts else ""
            console.print(f"  - {h.name} ({h.hypothesis_type.value}){conflict}")
    finally:
        db.close()


@hypothesis_app.command("list")
def hypothesis_list(
    goal_id: str = typer.Argument(...),
    status: Optional[HypothesisStatusEnum] = typer.Option(None, "--status", "-s"),
    hyp_type: Optional[HypothesisTypeEnum] = typer.Option(None, "--type", "-t"),
):
    """List hypothesis cards for a goal."""
    db = _get_session()
    try:
        items, total = hypothesis_svc.list_hypotheses(
            db, goal_id, status=status, hypothesis_type=hyp_type,
        )
        table = Table(title=f"Hypothesis Cards ({total} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Status", style="green")
        table.add_column("Conflicts")
        table.add_column("Approaches", justify="right")
        for h in items:
            table.add_row(
                h.id,
                h.name,
                h.hypothesis_type.value,
                h.status.value,
                "Yes" if h.has_conflicts else "No",
                str(len(h.approach_ids)),
            )
        console.print(table)
    finally:
        db.close()


@hypothesis_app.command("show")
def hypothesis_show(hypothesis_id: str = typer.Argument(...)):
    """Show full details of a hypothesis card."""
    db = _get_session()
    try:
        result = hypothesis_svc.get(db, hypothesis_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@hypothesis_app.command("review")
def hypothesis_review(hypothesis_id: str = typer.Argument(...)):
    """Transition hypothesis card to 'reviewed' status."""
    db = _get_session()
    try:
        result = hypothesis_svc.transition(db, hypothesis_id, HypothesisStatusEnum.reviewed)
        console.print(f"[green]Hypothesis {hypothesis_id[:8]}… is now {result.status.value}[/green]")
    finally:
        db.close()


@hypothesis_app.command("delete")
def hypothesis_delete(
    hypothesis_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a generated hypothesis card."""
    if not yes:
        typer.confirm(f"Delete hypothesis {hypothesis_id}?", abort=True)
    db = _get_session()
    try:
        hypothesis_svc.delete(db, hypothesis_id)
        console.print(f"[red]Hypothesis {hypothesis_id[:8]}… deleted[/red]")
    finally:
        db.close()


# --- Experiment commands ---


@experiment_app.command("generate")
def experiment_generate(
    goal_id: str = typer.Argument(...),
    approach: Optional[str] = typer.Option(None, "--approach", "-a", help="Specific approach ID"),
    hypothesis: Optional[str] = typer.Option(None, "--hypothesis", "-h", help="Hypothesis ID"),
    max_experiments: int = typer.Option(10, "--max", "-m"),
    include_measurement: bool = typer.Option(False, "--include-measurement"),
):
    """Generate experiment cards from scored approaches."""
    db = _get_session()
    try:
        request = ExperimentGenerateRequest(
            approach_ids=[approach] if approach else None,
            hypothesis_id=hypothesis,
            include_measurement=include_measurement,
            max_experiments=max_experiments,
        )
        result = experiment_svc.generate_experiments(db, goal_id, request)
        console.print(f"[green]Generation run {result.generation_run_id[:8]}… complete[/green]")
        console.print(f"  Experiments created: {result.experiments_created}")
        console.print(f"  Simulation: {result.simulation_count}")
        console.print(f"  Measurement: {result.measurement_count}")
        console.print(f"  Duplicates skipped: {result.experiments_skipped_duplicate}")
        for e in result.experiments:
            console.print(f"  - {e.name} ({e.experiment_type.value}) sweep={e.parameter_sweep_count}")
    finally:
        db.close()


@experiment_app.command("list")
def experiment_list(
    goal_id: str = typer.Argument(...),
    status: Optional[ExperimentStatusEnum] = typer.Option(None, "--status", "-s"),
    exp_type: Optional[ExperimentTypeEnum] = typer.Option(None, "--type", "-t"),
):
    """List experiment cards for a goal."""
    db = _get_session()
    try:
        items, total = experiment_svc.list_experiments(
            db, goal_id, status=status, experiment_type=exp_type,
        )
        table = Table(title=f"Experiment Cards ({total} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Status", style="green")
        table.add_column("Approaches", justify="right")
        table.add_column("Sweep", justify="right")
        for e in items:
            table.add_row(
                e.id,
                e.name,
                e.experiment_type.value,
                e.status.value,
                str(len(e.approach_ids)),
                str(e.parameter_sweep_count or 0),
            )
        console.print(table)
    finally:
        db.close()


@experiment_app.command("show")
def experiment_show(experiment_id: str = typer.Argument(...)):
    """Show full details of an experiment card."""
    db = _get_session()
    try:
        result = experiment_svc.get(db, experiment_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@experiment_app.command("review")
def experiment_review(experiment_id: str = typer.Argument(...)):
    """Transition experiment card to 'reviewed' status."""
    db = _get_session()
    try:
        result = experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.reviewed)
        console.print(f"[green]Experiment {experiment_id[:8]}… is now {result.status.value}[/green]")
    finally:
        db.close()


@experiment_app.command("approve")
def experiment_approve(experiment_id: str = typer.Argument(...)):
    """Transition experiment card to 'approved' status."""
    db = _get_session()
    try:
        result = experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.approved)
        console.print(f"[green]Experiment {experiment_id[:8]}… is now {result.status.value}[/green]")
    finally:
        db.close()


@experiment_app.command("run")
def experiment_run(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Seconds to wait for the repro run"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON result"),
):
    """Run an approved experiment on the repro simulator and validate real metrics."""
    db = _get_session()
    try:
        result = runner_svc.run_experiment(db, experiment_id, goal_id, timeout=timeout)
        if json_out:
            console.print_json(result.model_dump_json(indent=2))
            return
        console.print(f"[green]Ran {result.simulator} → run {result.run_id[:8]}… ({result.repro_status})[/green]")
        if result.measured_metrics:
            table = Table(title="Measured Metrics (canonical)")
            table.add_column("Metric")
            table.add_column("Value", justify="right")
            for name, value in result.measured_metrics.items():
                table.add_row(name, f"{value:.4g}")
            console.print(table)
        v = result.validation
        decision_color = "green" if v.decision.value == "validated" else "red"
        console.print(f"[{decision_color}]Validation: {v.decision.value.upper()}[/{decision_color}] (confidence {v.confidence:.2f})")
        console.print(f"Reasoning: {v.reasoning}")
    finally:
        db.close()


@experiment_app.command("delete")
def experiment_delete(
    experiment_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a generated experiment card."""
    if not yes:
        typer.confirm(f"Delete experiment {experiment_id}?", abort=True)
    db = _get_session()
    try:
        experiment_svc.delete(db, experiment_id)
        console.print(f"[red]Experiment {experiment_id[:8]}… deleted[/red]")
    finally:
        db.close()


@experiment_app.command("export")
def experiment_export(
    experiment_id: str = typer.Argument(...),
    fmt: str = typer.Option("yaml", "--format", "-f", help="Export format: yaml or python"),
):
    """Export experiment card as YAML or Python config."""
    db = _get_session()
    try:
        result = experiment_svc.export_experiment(db, experiment_id, fmt)
        console.print(result.content)
    finally:
        db.close()


@experiment_app.command("score")
def experiment_score(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Score an experiment card against the experiment rubric."""
    db = _get_session()
    try:
        result = experiment_svc.score_experiment(db, experiment_id, goal_id)
        table = Table(title=f"Experiment Score: {experiment_id[:8]}…")
        table.add_column("Dimension")
        table.add_column("Score", justify="right")
        table.add_column("Weight", justify="right")
        table.add_column("Weighted", justify="right")
        table.add_column("Rationale", max_width=50)
        for d in result.dimensions:
            table.add_row(
                d.dimension.value,
                f"{d.score:.3f}",
                f"{d.weight:.2f}",
                f"{d.weighted_score:.4f}",
                d.rationale,
            )
        console.print(table)
        console.print(f"[bold]Total score: {result.total_score:.4f}[/bold]")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Approval commands
# ---------------------------------------------------------------------------

@approval_app.command("pending")
def approval_pending(
    goal_id: str | None = typer.Option(None, "--goal", help="Filter by goal ID"),
):
    """List experiments awaiting approval (status=reviewed)."""
    from coscientist.schemas.approval import ApprovalDecisionCreate, ApprovalDecisionEnum
    db = _get_session()
    try:
        experiments = approval_svc.list_pending(db, goal_id=goal_id)
        table = Table(title="Pending Experiments")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Goal")
        table.add_column("Type")
        table.add_column("Cost")
        for e in experiments:
            table.add_row(e.id, e.name, e.workspace_id, e.experiment_type.value, e.estimated_cost)
        console.print(table)
        console.print(f"[bold]{len(experiments)} experiment(s) pending approval[/bold]")
    finally:
        db.close()


@approval_app.command("approve")
def approval_approve(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    reviewer_id: str | None = typer.Option(None, "--reviewer"),
    reason: str | None = typer.Option(None, "--reason"),
):
    """Approve an experiment (transitions to approved, stores YAML handoff)."""
    from coscientist.schemas.approval import ApprovalDecisionCreate, ApprovalDecisionEnum
    db = _get_session()
    try:
        body = ApprovalDecisionCreate(
            decision=ApprovalDecisionEnum.approve,
            reviewer_id=reviewer_id,
            reason=reason,
        )
        decision = approval_svc.record_decision(db, experiment_id, goal_id, body)
        console.print(f"[green]Approved[/green] experiment {experiment_id[:8]}… → [bold]approved[/bold]")
        console.print(f"Decision ID: {decision.id}")
    finally:
        db.close()


@approval_app.command("reject")
def approval_reject(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", help="Required reason for rejection"),
    reviewer_id: str | None = typer.Option(None, "--reviewer"),
):
    """Reject an experiment (transitions to superseded)."""
    from coscientist.schemas.approval import ApprovalDecisionCreate, ApprovalDecisionEnum
    db = _get_session()
    try:
        body = ApprovalDecisionCreate(
            decision=ApprovalDecisionEnum.reject,
            reviewer_id=reviewer_id,
            reason=reason,
        )
        decision = approval_svc.record_decision(db, experiment_id, goal_id, body)
        console.print(f"[red]Rejected[/red] experiment {experiment_id[:8]}… → [bold]superseded[/bold]")
        console.print(f"Decision ID: {decision.id}")
    finally:
        db.close()


@approval_app.command("request-edit")
def approval_request_edit(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", help="Required reason for requesting edits"),
    reviewer_id: str | None = typer.Option(None, "--reviewer"),
):
    """Request edits on an experiment (transitions back to generated)."""
    from coscientist.schemas.approval import ApprovalDecisionCreate, ApprovalDecisionEnum
    db = _get_session()
    try:
        body = ApprovalDecisionCreate(
            decision=ApprovalDecisionEnum.request_edit,
            reviewer_id=reviewer_id,
            reason=reason,
        )
        decision = approval_svc.record_decision(db, experiment_id, goal_id, body)
        console.print(f"[yellow]Edit requested[/yellow] for experiment {experiment_id[:8]}… → [bold]generated[/bold]")
        console.print(f"Decision ID: {decision.id}")
    finally:
        db.close()


@approval_app.command("history")
def approval_history(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Show chronological decision history for an experiment."""
    db = _get_session()
    try:
        result = approval_svc.list_decisions(db, experiment_id, goal_id)
        table = Table(title=f"Decision History: {experiment_id[:8]}…")
        table.add_column("ID")
        table.add_column("Decision")
        table.add_column("Reviewer")
        table.add_column("Reason", max_width=50)
        table.add_column("Created")
        for d in result.items:
            table.add_row(
                d.id,
                d.decision.value,
                d.reviewer_id or "—",
                (d.reason or "—")[:80],
                d.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)
        console.print(f"[bold]{result.total} decision(s)[/bold]")
    finally:
        db.close()


@approval_app.command("duplicate")
def approval_duplicate(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Create an editable copy of an experiment (new card with status=generated)."""
    db = _get_session()
    try:
        result = approval_svc.duplicate_experiment(db, experiment_id, goal_id)
        console.print(f"[green]Duplicated[/green] {result.original_id[:8]}… → {result.new_id[:8]}…")
        console.print(f"New experiment: [bold]{result.new_experiment.name}[/bold] (status=generated)")
    finally:
        db.close()


@approval_app.command("submit")
def approval_submit(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    mode: str = typer.Option("approve_batch", "--mode", help="approve_batch | approve_each_run | approval_required_above_threshold"),
    approver: str | None = typer.Option(None, "--approver"),
    threshold: int | None = typer.Option(None, "--threshold", help="run count above which per-run approval is required"),
    credentialed: bool = typer.Option(False, "--credentialed"),
):
    """Submit an approved experiment to the Experimentation System as RunRequest(s)."""
    from coscientist.schemas.approval import ApprovalModeEnum, SubmissionRequest
    from coscientist.services import submission as submission_svc
    db = _get_session()
    try:
        body = SubmissionRequest(
            approval_mode=ApprovalModeEnum(mode),
            approver=approver,
            approval_threshold=threshold,
            credentialed=credentialed,
        )
        result = submission_svc.submit_experiment(db, experiment_id, goal_id, body)
        console.print(
            f"[green]Submitted[/green] experiment {experiment_id[:8]}… → batch {result.execution_batch_id[:8]}…"
        )
        console.print(
            f"{result.run_request_count} RunRequest(s), execution_status=[bold]{result.execution_status}[/bold]"
        )
    finally:
        db.close()


@approval_app.command("retry")
def approval_retry(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    approver: str | None = typer.Option(None, "--approver"),
):
    """Retry a failed handoff into the same batch, without creating duplicate RunRequests."""
    from fastapi import HTTPException

    from coscientist.schemas.approval import SubmissionRequest
    from coscientist.services import submission as submission_svc
    db = _get_session()
    try:
        body = SubmissionRequest(approver=approver)
        result = submission_svc.submit_experiment(db, experiment_id, goal_id, body)
        console.print(
            f"[green]Retried[/green] experiment {experiment_id[:8]}… → batch {result.execution_batch_id[:8]}…"
        )
        console.print(
            f"{result.run_request_count} RunRequest(s), handoff_status=[bold]{result.handoff_status}[/bold]"
        )
    except HTTPException as exc:
        console.print(f"[red]Retry failed[/red] ({exc.status_code}): {exc.detail}")
        raise typer.Exit(code=1)
    finally:
        db.close()


@approval_app.command("cancel")
def approval_cancel(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    requester: str | None = typer.Option(None, "--requester"),
    reason: str | None = typer.Option(None, "--reason"),
):
    """Relay a cancellation request to the Experimentation System and record its status.

    The co-scientist does not stop execution itself — control stays with that system.
    """
    from fastapi import HTTPException

    from coscientist.services import handoff as handoff_svc
    db = _get_session()
    try:
        result = handoff_svc.request_cancellation(
            db, experiment_id, goal_id, requester=requester, reason=reason
        )
        console.print(
            f"[yellow]Cancellation requested[/yellow] for experiment {experiment_id[:8]}… → status [bold]{result.status.value}[/bold]"
        )
        console.print(f"Handoff request ID: {result.id}")
    except HTTPException as exc:
        console.print(f"[red]Cancel failed[/red] ({exc.status_code}): {exc.detail}")
        raise typer.Exit(code=1)
    finally:
        db.close()


@approval_app.command("resubmit")
def approval_resubmit(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    requester: str | None = typer.Option(None, "--requester"),
    reason: str | None = typer.Option(None, "--reason"),
):
    """Relay a resubmission request to the Experimentation System and record its status.

    The co-scientist does not re-run experiments itself — control stays with that system.
    """
    from fastapi import HTTPException

    from coscientist.services import handoff as handoff_svc
    db = _get_session()
    try:
        result = handoff_svc.request_resubmission(
            db, experiment_id, goal_id, requester=requester, reason=reason
        )
        console.print(
            f"[cyan]Resubmission requested[/cyan] for experiment {experiment_id[:8]}… → status [bold]{result.status.value}[/bold]"
        )
        console.print(f"Handoff request ID: {result.id}")
    except HTTPException as exc:
        console.print(f"[red]Resubmit failed[/red] ({exc.status_code}): {exc.detail}")
        raise typer.Exit(code=1)
    finally:
        db.close()


@approval_app.command("handoff-requests")
def approval_handoff_requests(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """List recorded handoff-control requests (failed handoffs, retries, cancel/resubmit)."""
    from coscientist.services import handoff as handoff_svc
    db = _get_session()
    try:
        result = handoff_svc.list_handoff_requests(db, experiment_id)
        table = Table(title=f"Handoff Requests: {experiment_id[:8]}…")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Retryable")
        table.add_column("Runs")
        table.add_column("Detail", max_width=50)
        table.add_column("Created")
        for h in result.items:
            detail = h.error or (
                h.payload_summary.get("reason") if h.payload_summary else None
            ) or "—"
            table.add_row(
                h.request_type.value,
                h.status.value,
                "yes" if h.retryable else "—",
                str(len(h.run_request_ids)),
                str(detail)[:80],
                h.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)
        console.print(f"[bold]{result.total} handoff request(s)[/bold]")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Validation commands
# ---------------------------------------------------------------------------

@validation_app.command("submit")
def validation_submit(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    metrics: str = typer.Option(..., "--metrics", "-m", help="JSON dict of metric name→value, e.g. '{\"acoustic_contrast\": 18.5}'"),
    artifacts: Optional[str] = typer.Option(None, "--artifacts", "-a", help="JSON dict of artifact type→path"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Optional experimenter notes"),
):
    """Submit measured results and trigger the Claude validation agent."""
    from coscientist.schemas.validation import ExperimentResultSubmission
    db = _get_session()
    try:
        measured = json.loads(metrics)
        artifact_paths = json.loads(artifacts) if artifacts else None
        submission = ExperimentResultSubmission(
            measured_metrics=measured,
            artifact_paths=artifact_paths,
            notes=notes,
        )
        result = validation_svc.submit_results(db, experiment_id, goal_id, submission)
        decision_color = "green" if result.decision.value == "validated" else "red"
        console.print(f"[{decision_color}]Decision: {result.decision.value.upper()}[/{decision_color}]")
        console.print(f"Confidence: {result.confidence:.2f}")
        console.print(f"Reasoning: {result.reasoning}")
        if result.criterion_results:
            table = Table(title="Criterion Results")
            table.add_column("Criterion")
            table.add_column("Measured")
            table.add_column("Target")
            table.add_column("Operator")
            table.add_column("Unit")
            table.add_column("Passed")
            for cr in result.criterion_results:
                passed_str = "[green]Yes[/green]" if cr.passed else "[red]No[/red]"
                table.add_row(
                    cr.name,
                    str(cr.measured) if cr.measured is not None else "N/A",
                    str(cr.target),
                    cr.operator,
                    cr.unit,
                    passed_str,
                )
            console.print(table)
        if result.refinement_suggestions:
            console.print("[yellow]Refinement suggestions:[/yellow]")
            for s in result.refinement_suggestions:
                console.print(f"  - {s}")
    finally:
        db.close()


@validation_app.command("show")
def validation_show(
    experiment_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Show the validation result for an experiment."""
    db = _get_session()
    try:
        result = validation_svc.get_result(db, experiment_id, goal_id)
        if result is None:
            console.print(f"[yellow]No validation result found for experiment {experiment_id}[/yellow]")
            raise typer.Exit(code=1)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@validation_app.command("list")
def validation_list(
    goal_id: str = typer.Argument(...),
):
    """List all validation results for a goal."""
    db = _get_session()
    try:
        result = validation_svc.list_results(db, goal_id)
        table = Table(title=f"Validation Results ({result.total} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Experiment")
        table.add_column("Approach")
        table.add_column("Decision", style="bold")
        table.add_column("Confidence", justify="right")
        table.add_column("Created")
        for r in result.items:
            decision_color = "green" if r.decision.value == "validated" else "red"
            table.add_row(
                r.id,
                r.experiment_id,
                r.approach_id,
                f"[{decision_color}]{r.decision.value}[/{decision_color}]",
                f"{r.confidence:.2f}",
                r.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Device commands
# ---------------------------------------------------------------------------

@device_app.command("generate")
def device_generate(
    goal_id: str = typer.Argument(...),
    approach: Optional[list[str]] = typer.Option(None, "--approach", "-a", help="Approach IDs to use (default: all validated)"),
):
    """Generate candidate device concepts from validated approaches via agent."""
    db = _get_session()
    try:
        request = DeviceConceptGenerateRequest(approach_ids=approach or [])
        result = device_svc.generate(db, goal_id, request)
        if result.generated == 0:
            console.print("[yellow]No device concepts generated. Ensure the goal has validated or scored approaches.[/yellow]")
            return
        table = Table(title=f"Generated Device Concepts ({result.generated}) — run {result.generation_run_id[:8]}")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Form Factor")
        table.add_column("Maturity")
        table.add_column("Risks", justify="right")
        table.add_column("Next Steps", justify="right")
        for c in result.items:
            table.add_row(
                c.id,
                c.name,
                c.form_factor.type,
                c.maturity.value,
                str(len(c.unresolved_risks)),
                str(len(c.next_steps)),
            )
        console.print(table)
    finally:
        db.close()


@device_app.command("list")
def device_list(
    goal_id: str = typer.Argument(...),
    status: Optional[DeviceConceptStatusEnum] = typer.Option(None, "--status", "-s"),
):
    """List device concept cards for a goal."""
    db = _get_session()
    try:
        result = device_svc.list_devices(db, goal_id, status)
        table = Table(title=f"Device Concepts ({result.total} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Form Factor")
        table.add_column("Maturity")
        table.add_column("Status")
        table.add_column("Approaches", justify="right")
        for c in result.items:
            status_color = {"generated": "white", "reviewed": "green", "superseded": "dim"}.get(c.status.value, "white")
            table.add_row(
                c.id,
                c.name,
                c.form_factor.type,
                c.maturity.value,
                f"[{status_color}]{c.status.value}[/{status_color}]",
                str(len(c.approach_ids)),
            )
        console.print(table)
    finally:
        db.close()


@device_app.command("show")
def device_show(
    device_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Show full details of a device concept card."""
    db = _get_session()
    try:
        result = device_svc.get(db, device_id, goal_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@device_app.command("review")
def device_review(
    device_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Transition a device concept to 'reviewed'."""
    db = _get_session()
    try:
        result = device_svc.transition(db, device_id, goal_id, DeviceConceptStatusEnum.reviewed)
        console.print(f"[green]Device concept {device_id} transitioned to '{result.status.value}'.[/green]")
    finally:
        db.close()


@device_app.command("compare")
def device_compare(
    device_ids: list[str] = typer.Argument(..., help="Two or more device IDs to compare"),
    goal_id: str = typer.Option(..., "--goal", "-g", help="Goal ID"),
):
    """Compare multiple device concepts side by side."""
    db = _get_session()
    try:
        result = device_svc.compare(db, goal_id, list(device_ids))
        table = Table(title="Device Concept Comparison")
        table.add_column("Dimension", style="bold")
        for concept in result.concepts:
            table.add_column(concept.name[:30], style="cyan")
        for dim in result.dimensions:
            row = [dim] + [concept.values.get(dim, "") for concept in result.concepts]
            table.add_row(*row)
        console.print(table)
    finally:
        db.close()


@device_app.command("export")
def device_export(
    device_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
    format: str = typer.Option("markdown", "--format", "-f", help="Export format: markdown or json"),
):
    """Export a device concept card as markdown or JSON."""
    db = _get_session()
    try:
        result = device_svc.export_device(db, device_id, goal_id, format)
        console.print(result.content)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Roadmap commands
# ---------------------------------------------------------------------------

@roadmap_app.command("generate")
def roadmap_generate(goal_id: str = typer.Argument(...)):
    """Generate next-best research actions for a goal via agent."""
    db = _get_session()
    try:
        result = roadmap_svc.generate(db, goal_id)
        if result.total == 0:
            console.print("[yellow]No roadmap items generated — ensure the goal has at least one approach.[/yellow]")
            return
        console.print(f"[green]Generation run {result.generation_run_id[:8]}… — {result.total} items[/green]")
        table = Table(title=f"Research Roadmap ({result.total} items)")
        table.add_column("Rank", justify="right")
        table.add_column("Lane", style="cyan")
        table.add_column("Title")
        table.add_column("Cost")
        table.add_column("Info Gain")
        table.add_column("Status", style="green")
        for item in result.items:
            table.add_row(
                str(item.priority_rank),
                item.lane.value,
                item.title,
                item.estimated_cost,
                item.estimated_information_gain,
                item.status.value,
            )
        console.print(table)
    finally:
        db.close()


@roadmap_app.command("list")
def roadmap_list(
    goal_id: str = typer.Argument(...),
    lane: Optional[RoadmapLaneEnum] = typer.Option(None, "--lane", "-l"),
    status: Optional[RoadmapStatusEnum] = typer.Option(None, "--status", "-s"),
):
    """List roadmap items for a goal, optionally filtered by lane or status."""
    db = _get_session()
    try:
        result = roadmap_svc.get_roadmap(db, goal_id, lane=lane, status=status)
        table = Table(title=f"Research Roadmap ({result.total} items)")
        table.add_column("Rank", justify="right")
        table.add_column("Lane", style="cyan")
        table.add_column("Title")
        table.add_column("Cost")
        table.add_column("Info Gain")
        table.add_column("Status", style="green")
        for item in result.items:
            table.add_row(
                str(item.priority_rank),
                item.lane.value,
                item.title,
                item.estimated_cost,
                item.estimated_information_gain,
                item.status.value,
            )
        console.print(table)
    finally:
        db.close()


@roadmap_app.command("show")
def roadmap_show(
    item_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Show full details of a roadmap item."""
    db = _get_session()
    try:
        result = roadmap_svc.get_item(db, item_id, goal_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@roadmap_app.command("complete")
def roadmap_complete(
    item_id: str = typer.Argument(...),
    goal_id: str = typer.Argument(...),
):
    """Transition a roadmap item to 'completed'."""
    db = _get_session()
    try:
        result = roadmap_svc.transition_item(db, item_id, goal_id, RoadmapStatusEnum.completed)
        console.print(f"[green]Roadmap item {item_id[:8]}… is now {result.status.value}[/green]")
    finally:
        db.close()


@roadmap_app.command("gaps")
def roadmap_gaps(goal_id: str = typer.Argument(...)):
    """Show structured evidence gaps per promising approach (CS-ROADMAP-003)."""
    db = _get_session()
    try:
        result = roadmap_svc.identify_evidence_gaps(db, goal_id)
        if result.total == 0:
            console.print("[green]No evidence gaps found.[/green]")
            return
        table = Table(title=f"Evidence Gaps ({result.total})", show_lines=True)
        table.add_column("Approach", style="cyan")
        table.add_column("Method family", style="dim")
        table.add_column("Missing evidence")
        table.add_column("Weak dimensions")
        table.add_column("Scored")
        for g in result.gaps:
            table.add_row(
                g.approach_name,
                g.method_family,
                ", ".join(g.missing_claim_fields) or "-",
                ", ".join(g.weak_dimensions) or "-",
                "no" if g.unscored else "yes",
            )
        console.print(table)
    finally:
        db.close()


@logs_app.command("list")
def logs_list(
    goal_id: str = typer.Argument(..., help="Goal ID"),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Filter by service (validation, device, roadmap)"),
    limit: int = typer.Option(50, "--limit", "-l"),
):
    """List agent action audit logs for a goal."""
    db = _get_session()
    try:
        result = governance_svc.list_logs(db, goal_id, service=service, limit=limit)
        if result.total == 0:
            console.print("[yellow]No agent action logs found.[/yellow]")
            return
        table = Table(title=f"Agent Action Logs ({result.total})", show_lines=False)
        table.add_column("ID", style="dim", width=10)
        table.add_column("Service", style="cyan")
        table.add_column("Action", style="white")
        table.add_column("Model", style="dim")
        table.add_column("Prompt tk", justify="right")
        table.add_column("Compl tk", justify="right")
        table.add_column("Elapsed ms", justify="right")
        table.add_column("Created", style="dim")
        for log in result.items:
            table.add_row(
                log.id[:8] + "…",
                log.service,
                log.action,
                log.model_used,
                str(log.prompt_tokens or "—"),
                str(log.completion_tokens or "—"),
                str(log.elapsed_ms or "—"),
                log.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)
    finally:
        db.close()


@logs_app.command("show")
def logs_show(
    log_id: str = typer.Argument(..., help="Log entry ID"),
    goal_id: str = typer.Argument(..., help="Goal ID"),
):
    """Show full details of an agent action log entry."""
    db = _get_session()
    try:
        result = governance_svc.get_log(db, log_id, goal_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


# --- Evaluation commands ---


def _gate(meets: bool) -> str:
    return "[green]PASS[/green]" if meets else "[red]FAIL[/red]"


@eval_app.command("approaches")
def eval_approaches(goal_id: str = typer.Argument(...)):
    """Approach Card usefulness and evidence traceability metrics (CS-EVAL-001)."""
    db = _get_session()
    try:
        m = evaluation_svc.approach_usefulness(db, goal_id)
        table = Table(title=f"Approach Usefulness ({m.total} cards)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Gate")
        table.add_row(
            "Usefulness",
            f"{m.usefulness_rate:.0%}",
            f"≥{m.usefulness_target:.0%}",
            _gate(m.usefulness_meets_target),
        )
        table.add_row(
            "Traceability",
            f"{m.traceability_rate:.0%}",
            f"≥{m.traceability_target:.0%}",
            _gate(m.traceability_meets_target),
        )
        console.print(table)
        console.print(
            f"useful={m.useful_count} discarded={m.discarded_count} "
            f"pending={m.pending_count} traceable={m.traceable_count}"
        )
    finally:
        db.close()


@eval_app.command("grounding")
def eval_grounding(goal_id: str = typer.Argument(...)):
    """Evidence grounding and unsupported claim rate (CS-EVAL-002)."""
    db = _get_session()
    try:
        m = evaluation_svc.evidence_grounding(db, goal_id)
        table = Table(title=f"Evidence Grounding ({m.total_claims} claims)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Gate")
        table.add_row(
            "Grounding",
            f"{m.grounding_rate:.0%}",
            f"≥{m.grounding_target:.0%}",
            _gate(m.grounding_meets_target),
        )
        table.add_row(
            "Unsupported",
            f"{m.unsupported_rate:.0%}",
            f"≤{m.unsupported_target:.0%}",
            _gate(m.unsupported_meets_target),
        )
        console.print(table)
        console.print(
            f"grounded={m.grounded} inferred={m.inferred} unsupported={m.unsupported}"
        )
        if m.unsupported_claims:
            unsupported = Table(title="Unsupported claims")
            unsupported.add_column("Approach")
            unsupported.add_column("Claim field")
            for c in m.unsupported_claims:
                unsupported.add_row(c.approach_name, c.claim_field)
            console.print(unsupported)
    finally:
        db.close()


@eval_app.command("experiments")
def eval_experiments(goal_id: str = typer.Argument(...)):
    """Experiment proposal acceptance and spec validity (CS-EVAL-003)."""
    db = _get_session()
    try:
        m = evaluation_svc.experiment_quality(db, goal_id)
        table = Table(title=f"Experiment Quality ({m.total} experiments)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Gate")
        table.add_row(
            "Acceptance",
            f"{m.acceptance_rate:.0%}",
            f"≥{m.acceptance_target:.0%}",
            _gate(m.acceptance_meets_target),
        )
        table.add_row(
            "Spec validity",
            f"{m.validity_rate:.0%}",
            f"≥{m.validity_target:.0%}",
            _gate(m.validity_meets_target),
        )
        console.print(table)
        console.print(
            f"accepted={m.accepted_count} discarded={m.discarded_count} "
            f"failed={m.failed_count} pending={m.pending_count}"
        )
    finally:
        db.close()


@eval_app.command("report")
def eval_report(goal_id: str = typer.Argument(...)):
    """Full evaluation report (CS-EVAL-001/002/003/005) as JSON."""
    db = _get_session()
    try:
        result = evaluation_svc.get_report(db, goal_id)
        console.print_json(result.model_dump_json(indent=2))
    finally:
        db.close()


@eval_app.command("productivity")
def eval_productivity(goal_id: str = typer.Argument(...)):
    """Research time saved and user satisfaction (CS-EVAL-005)."""
    db = _get_session()
    try:
        m = evaluation_svc.productivity(db, goal_id)
        table = Table(title="Productivity")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Agent actions", str(m.agent_action_count))
        table.add_row("Est. time saved (min)", str(m.estimated_time_saved_minutes))
        table.add_row("Est. time saved (hrs)", f"{m.estimated_time_saved_hours:.1f}")
        sat = "n/a" if m.satisfaction_rate is None else f"{m.satisfaction_rate:.0%}"
        table.add_row("Satisfaction", sat)
        table.add_row("Feedback (pos/total)", f"{m.positive_feedback}/{m.total_feedback}")
        console.print(table)
    finally:
        db.close()


@eval_app.command("handoff")
def eval_handoff(goal_id: str = typer.Argument(...)):
    """Execution handoff / RunRequest creation reliability (CS-EVAL-007)."""
    db = _get_session()
    try:
        m = evaluation_svc.handoff_success(db, goal_id)
        table = Table(title="Handoff Success")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Gate")
        table.add_row(
            "Handoff success",
            f"{m.handoff_success_rate:.0%}",
            f"≥{m.handoff_success_target:.0%}",
            _gate(m.handoff_success_meets_target),
        )
        console.print(table)
        retry = "n/a" if m.retry_success_rate is None else f"{m.retry_success_rate:.0%}"
        console.print(
            f"approved={m.approved_experiments} attempted={m.attempted_handoffs} "
            f"successful={m.successful_handoffs} failed={m.failed_handoffs} "
            f"run_requests={m.successful_run_requests} retry_success={retry}"
        )
    finally:
        db.close()


@eval_app.command("traceability")
def eval_traceability(goal_id: str = typer.Argument(...)):
    """RunRequest traceability back to research intent (CS-EVAL-008)."""
    db = _get_session()
    try:
        m = evaluation_svc.execution_traceability(db, goal_id)
        table = Table(title=f"Execution Traceability ({m.total_run_requests} run requests)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Gate")
        table.add_row(
            "Fully traceable",
            f"{m.traceability_rate:.0%}",
            f"≥{m.traceability_target:.0%}",
            _gate(m.traceability_meets_target),
        )
        console.print(table)
        console.print(
            f"goal={m.linked_to_goal} experiment={m.linked_to_experiment} "
            f"approach={m.linked_to_approach} hypothesis={m.linked_to_hypothesis}"
            f"/{m.hypothesis_applicable} approval={m.linked_to_approval}"
        )
    finally:
        db.close()


@eval_app.command("duplicates")
def eval_duplicates(goal_id: str = typer.Argument(...)):
    """Duplicate ingestion / score-update rate — idempotency check (CS-EVAL-009)."""
    db = _get_session()
    try:
        m = evaluation_svc.duplicate_ingestion(db, goal_id)
        table = Table(title="Duplicate Ingestion")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Gate")
        table.add_row(
            "Duplicate bundles",
            str(m.duplicate_bundle_count),
            _gate(m.duplicate_bundle_count == 0),
        )
        table.add_row(
            "Duplicate score updates",
            str(m.duplicate_score_update_count),
            _gate(m.duplicate_score_update_count == 0),
        )
        console.print(table)
        console.print(
            f"bundles={m.total_result_bundles} distinct_keys={m.distinct_ingestion_keys} "
            f"score_updates={m.total_score_updates} distinct={m.distinct_score_update_keys}"
        )
    finally:
        db.close()


@eval_app.command("freshness")
def eval_freshness(goal_id: str = typer.Argument(...)):
    """Execution-status freshness — stale in-flight RunRequests (CS-EVAL-010)."""
    db = _get_session()
    try:
        m = evaluation_svc.status_freshness(db, goal_id)
        table = Table(title="Status Freshness")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Gate")
        table.add_row("Stale in-flight run requests", str(m.stale_run_requests), _gate(m.meets_target))
        console.print(table)
        max_s = "n/a" if m.max_staleness_seconds is None else f"{m.max_staleness_seconds:.0f}s"
        mean_s = "n/a" if m.mean_staleness_seconds is None else f"{m.mean_staleness_seconds:.0f}s"
        console.print(
            f"total={m.total_run_requests} in_flight={m.in_flight_run_requests} "
            f"max={max_s} mean={mean_s} threshold={m.threshold_seconds}s"
        )
    finally:
        db.close()


@eval_app.command("failed-usefulness")
def eval_failed_usefulness(goal_id: str = typer.Argument(...)):
    """Failed-run usefulness — failures that still guide next work (CS-EVAL-011)."""
    db = _get_session()
    try:
        m = evaluation_svc.failed_run_usefulness(db, goal_id)
        table = Table(title=f"Failed-Run Usefulness ({m.failed_run_count} failed runs)")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Target", justify="right")
        table.add_column("Gate")
        table.add_row(
            "Useful failures",
            f"{m.usefulness_rate:.0%}",
            f"≥{m.usefulness_target:.0%}",
            _gate(m.meets_target),
        )
        console.print(table)
        console.print(
            f"reason={m.with_failure_reason} artifacts={m.with_artifacts} "
            f"retryable={m.retryable_count} roadmap={m.with_roadmap_action} useful={m.useful_count}"
        )
    finally:
        db.close()


@eval_app.command("batch-quality")
def eval_batch_quality(goal_id: str = typer.Argument(...)):
    """Batch aggregation quality — completion/partial/mixed rates (CS-EVAL-012)."""
    db = _get_session()
    try:
        m = evaluation_svc.batch_aggregation_quality(db, goal_id)
        table = Table(title="Batch Aggregation Quality")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Batch completion", f"{m.batch_completion_rate:.0%}")
        table.add_row("Partial aggregation", f"{m.partial_aggregation_rate:.0%}")
        table.add_row("Mixed outcome", f"{m.mixed_outcome_rate:.0%}")
        console.print(table)
        console.print(
            f"batches={m.total_batches} completed={m.completed_batches} "
            f"aggregations={m.total_aggregations} partial={m.partial_aggregations} "
            f"mixed={m.mixed_aggregations}"
        )
    finally:
        db.close()


@feedback_app.command("add")
def feedback_add(
    goal_id: str = typer.Argument(...),
    target_type: str = typer.Argument(..., help="approach|score|experiment|device|hypothesis|roadmap"),
    target_id: str = typer.Argument(...),
    up: bool = typer.Option(False, "--up/--down", help="Thumbs up (default down)"),
    comment: Optional[str] = typer.Option(None, "--comment", "-c"),
    reviewer: Optional[str] = typer.Option(None, "--reviewer"),
):
    """Record thumbs up/down feedback on a generated artifact (CS-EVAL-006)."""
    db = _get_session()
    try:
        data = FeedbackCreate(
            target_type=FeedbackTargetEnum(target_type),
            target_id=target_id,
            is_positive=up,
            comment=comment,
            reviewer_id=reviewer,
        )
        result = feedback_svc.create(db, goal_id, data)
        vote = "up" if result.is_positive else "down"
        console.print(f"[{vote}] feedback {result.id} on {result.target_type.value} {result.target_id}")
    finally:
        db.close()


@feedback_app.command("list")
def feedback_list(
    goal_id: str = typer.Argument(...),
    target_type: Optional[str] = typer.Option(None, "--type"),
    target_id: Optional[str] = typer.Option(None, "--target"),
):
    """List feedback for a goal (CS-EVAL-006)."""
    db = _get_session()
    try:
        tt = FeedbackTargetEnum(target_type) if target_type else None
        result = feedback_svc.list_feedback(db, goal_id, target_type=tt, target_id=target_id)
        table = Table(title=f"Feedback ({result.total})")
        table.add_column("Vote")
        table.add_column("Target type")
        table.add_column("Target ID")
        table.add_column("Comment")
        for f in result.items:
            table.add_row(
                "up" if f.is_positive else "down",
                f.target_type.value,
                f.target_id,
                f.comment or "",
            )
        console.print(table)
    finally:
        db.close()
