from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.database import get_db
from coscientist.schemas.approach import (
    ApproachCardUpdate,
    ApproachMergeRequest,
    ApproachStatusEnum,
)
from coscientist.schemas.experiment import ExperimentCardUpdate
from coscientist.schemas.hypothesis import HypothesisStatusEnum
from coscientist.services import approach as approach_svc
from coscientist.services import approach_evidence as approach_evidence_svc
from coscientist.services import device as device_svc
from coscientist.services import evaluation as evaluation_svc
from coscientist.services import execution as execution_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc
from coscientist.services import handoff as handoff_svc
from coscientist.services import hypothesis as hypothesis_svc
from coscientist.services import result_bundle as result_bundle_svc
from coscientist.services import roadmap as roadmap_svc
from coscientist.services import scout as scout_svc
from coscientist.services import score as score_svc
from coscientist.services import score_update as score_update_svc
from coscientist.services import validation as validation_svc
from coscientist.web.templates import templates

router = APIRouter(prefix="/ui", tags=["ui"], include_in_schema=False)


def _error(request: Request, exc: HTTPException) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


# --- Goals & dashboard (CS-UI-001) ---


@router.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse(url="/ui/goals", status_code=303)


@router.get("/goals", response_class=HTMLResponse)
def goals_page(
    request: Request, show_archived: bool = False, db: Session = Depends(get_db)
):
    items, _ = goal_svc.list_goals(db, limit=100)
    if not show_archived:
        items = [g for g in items if g.status.value != "archived"]
    return templates.TemplateResponse(
        request, "goals.html", {"goals": items, "show_archived": show_archived}
    )


@router.get("/goals/{goal_id}", response_class=HTMLResponse)
def dashboard(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    _, evidence_total = scout_svc.get_evidence(db, goal_id, limit=1)
    _, approach_total = approach_svc.list_approaches(db, goal_id, limit=1)
    _, hypothesis_total = hypothesis_svc.list_hypotheses(db, goal_id, limit=1)
    _, experiment_total = experiment_svc.list_experiments(db, goal_id, limit=1)
    counts = {
        "evidence": evidence_total,
        "approaches": approach_total,
        "hypotheses": hypothesis_total,
        "experiments": experiment_total,
        "validation": validation_svc.list_results(db, goal_id).total,
        "devices": device_svc.list_devices(db, goal_id, limit=1).total,
        "roadmap": roadmap_svc.get_roadmap(db, goal_id, limit=1).total,
    }
    return templates.TemplateResponse(
        request, "dashboard.html", {"goal": goal, "counts": counts}
    )


@router.get("/goals/{goal_id}/evidence", response_class=HTMLResponse)
def evidence_page(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    items, total = scout_svc.get_evidence(db, goal_id, limit=200)
    return templates.TemplateResponse(
        request, "evidence.html", {"goal": goal, "evidence": items, "total": total}
    )


# --- Approaches (CS-UI-002, CS-UI-003) ---


@router.get("/goals/{goal_id}/approaches", response_class=HTMLResponse)
def approaches_page(
    request: Request,
    goal_id: str,
    show_superseded: bool = False,
    db: Session = Depends(get_db),
):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    items, _ = approach_svc.list_approaches(db, goal_id, limit=200)
    superseded_count = sum(
        1 for a in items if a.status.value == "superseded"
    )
    if not show_superseded:
        items = [a for a in items if a.status.value != "superseded"]
    return templates.TemplateResponse(
        request,
        "approaches.html",
        {
            "goal": goal,
            "approaches": items,
            "total": len(items),
            "show_superseded": show_superseded,
            "superseded_count": superseded_count,
        },
    )


@router.get("/goals/{goal_id}/approaches/{approach_id}", response_class=HTMLResponse)
def approach_detail(
    request: Request, goal_id: str, approach_id: str, db: Session = Depends(get_db)
):
    try:
        goal = goal_svc.get(db, goal_id)
        approach = approach_svc.get(db, approach_id)
    except HTTPException as exc:
        return _error(request, exc)
    score = _try_get_scores(db, approach_id)
    evidence = approach_evidence_svc.build_execution_evidence(db, approach_id)
    return templates.TemplateResponse(
        request,
        "approach_detail.html",
        {"goal": goal, "approach": approach, "score": score, "evidence": evidence},
    )


@router.get(
    "/goals/{goal_id}/approaches/{approach_id}/score-panel",
    response_class=HTMLResponse,
)
def score_panel(
    request: Request, goal_id: str, approach_id: str, db: Session = Depends(get_db)
):
    try:
        goal = goal_svc.get(db, goal_id)
        approach = approach_svc.get(db, approach_id)
    except HTTPException as exc:
        return _error(request, exc)
    score = _try_get_scores(db, approach_id)
    return templates.TemplateResponse(
        request,
        "partials/score_panel.html",
        {"goal": goal, "approach": approach, "score": score},
    )


@router.post(
    "/goals/{goal_id}/approaches/{approach_id}/review", response_class=HTMLResponse
)
def approach_review(
    request: Request, goal_id: str, approach_id: str, db: Session = Depends(get_db)
):
    try:
        goal = goal_svc.get(db, goal_id)
        approach_svc.transition(db, approach_id, ApproachStatusEnum.reviewed)
        a = approach_svc.get(db, approach_id)
    except HTTPException as exc:
        return _error(request, exc)
    return templates.TemplateResponse(
        request, "partials/approach_card.html", {"goal": goal, "a": a}
    )


@router.post(
    "/goals/{goal_id}/approaches/{approach_id}/reject", response_class=HTMLResponse
)
def approach_reject(
    request: Request, goal_id: str, approach_id: str, db: Session = Depends(get_db)
):
    try:
        goal = goal_svc.get(db, goal_id)
        approach_svc.transition(db, approach_id, ApproachStatusEnum.superseded)
        a = approach_svc.get(db, approach_id)
    except HTTPException as exc:
        return _error(request, exc)
    return templates.TemplateResponse(
        request, "partials/approach_card.html", {"goal": goal, "a": a}
    )


@router.post(
    "/goals/{goal_id}/approaches/{approach_id}/score", response_class=HTMLResponse
)
def approach_score(
    request: Request, goal_id: str, approach_id: str, db: Session = Depends(get_db)
):
    try:
        goal = goal_svc.get(db, goal_id)
        approach = approach_svc.get(db, approach_id)
        score_svc.score_approach(db, approach_id)
        score = score_svc.get_scores(db, approach_id)
    except HTTPException as exc:
        return _error(request, exc)
    return templates.TemplateResponse(
        request,
        "partials/score_panel.html",
        {"goal": goal, "approach": approach, "score": score},
    )


@router.post("/goals/{goal_id}/approaches/merge", response_class=HTMLResponse)
def approach_merge(
    goal_id: str,
    source_approach_id: str = Form(...),
    target_approach_id: str = Form(...),
    db: Session = Depends(get_db),
):
    data = ApproachMergeRequest(
        source_approach_id=source_approach_id,
        target_approach_id=target_approach_id,
    )
    approach_svc.merge_approaches(db, data)
    return RedirectResponse(
        url=f"/ui/goals/{goal_id}/approaches", status_code=303
    )


@router.post("/goals/{goal_id}/approaches/{approach_id}", response_class=HTMLResponse)
def approach_edit(
    goal_id: str,
    approach_id: str,
    name: str = Form(...),
    problem_fit: str = Form(""),
    mechanism_summary: str = Form(""),
    device_relevance: str = Form(""),
    db: Session = Depends(get_db),
):
    data = ApproachCardUpdate(
        name=name,
        problem_fit=problem_fit or None,
        mechanism_summary=mechanism_summary or None,
        device_relevance=device_relevance or None,
    )
    approach_svc.update(db, approach_id, data)
    return RedirectResponse(
        url=f"/ui/goals/{goal_id}/approaches/{approach_id}", status_code=303
    )


# --- Hypotheses ---


@router.get("/goals/{goal_id}/hypotheses", response_class=HTMLResponse)
def hypotheses_page(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    items, total = hypothesis_svc.list_hypotheses(db, goal_id, limit=200)
    return templates.TemplateResponse(
        request,
        "hypotheses.html",
        {"goal": goal, "hypotheses": items, "total": total},
    )


@router.get("/goals/{goal_id}/hypotheses/{hypothesis_id}", response_class=HTMLResponse)
def hypothesis_detail(
    request: Request, goal_id: str, hypothesis_id: str, db: Session = Depends(get_db)
):
    try:
        goal = goal_svc.get(db, goal_id)
        hypothesis = hypothesis_svc.get(db, hypothesis_id)
    except HTTPException as exc:
        return _error(request, exc)
    return templates.TemplateResponse(
        request,
        "hypothesis_detail.html",
        {"goal": goal, "hypothesis": hypothesis},
    )


@router.post(
    "/goals/{goal_id}/hypotheses/{hypothesis_id}/review", response_class=HTMLResponse
)
def hypothesis_review(
    request: Request, goal_id: str, hypothesis_id: str, db: Session = Depends(get_db)
):
    try:
        goal = goal_svc.get(db, goal_id)
        hypothesis_svc.transition(db, hypothesis_id, HypothesisStatusEnum.reviewed)
        h = hypothesis_svc.get(db, hypothesis_id)
    except HTTPException as exc:
        return _error(request, exc)
    return templates.TemplateResponse(
        request, "partials/hypothesis_card.html", {"goal": goal, "h": h}
    )


# --- Experiments (CS-UI-004) ---


@router.get("/goals/{goal_id}/experiments", response_class=HTMLResponse)
def experiments_page(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    items, total = experiment_svc.list_experiments(db, goal_id, limit=200)
    return templates.TemplateResponse(
        request,
        "experiments.html",
        {"goal": goal, "experiments": items, "total": total},
    )


@router.get("/goals/{goal_id}/experiments/{experiment_id}", response_class=HTMLResponse)
def experiment_detail(
    request: Request,
    goal_id: str,
    experiment_id: str,
    saved: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    try:
        goal = goal_svc.get(db, goal_id)
        experiment = experiment_svc.get(db, experiment_id)
    except HTTPException as exc:
        return _error(request, exc)
    all_batches, _ = execution_svc.list_batches(db, goal_id, limit=200)
    batches = [b for b in all_batches if b.experiment_id == experiment_id]
    run_requests, _ = execution_svc.list_run_requests(db, experiment_id=experiment_id)
    aggregation = _try_get_aggregation(db, experiment_id)
    score_updates = score_update_svc.list_score_updates(
        db, goal_id, experiment_id=experiment_id
    ).items
    evidence_label = governance_svc.experiment_evidence_label(db, experiment_id)
    roadmap_items = roadmap_svc.list_for_experiment(db, experiment_id)
    handoff_requests = handoff_svc.list_handoff_requests(db, experiment_id).items
    return templates.TemplateResponse(
        request,
        "experiment_detail.html",
        {
            "goal": goal,
            "experiment": experiment,
            "saved": saved,
            "batches": batches,
            "run_requests": run_requests,
            "aggregation": aggregation,
            "score_updates": score_updates,
            "evidence_label": evidence_label,
            "roadmap_items": roadmap_items,
            "handoff_requests": handoff_requests,
        },
    )


@router.get(
    "/goals/{goal_id}/experiments/{experiment_id}/export", response_class=HTMLResponse
)
def experiment_export(
    request: Request,
    goal_id: str,
    experiment_id: str,
    fmt: str = Query(default="yaml"),
    db: Session = Depends(get_db),
):
    try:
        goal = goal_svc.get(db, goal_id)
        experiment = experiment_svc.get(db, experiment_id)
        export = experiment_svc.export_experiment(db, experiment_id, fmt=fmt)
    except HTTPException as exc:
        return _error(request, exc)
    return templates.TemplateResponse(
        request,
        "experiment_detail.html",
        {"goal": goal, "experiment": experiment, "export_content": export.content},
    )


@router.post("/goals/{goal_id}/experiments/{experiment_id}", response_class=HTMLResponse)
def experiment_edit(
    goal_id: str,
    experiment_id: str,
    name: str = Form(...),
    objective: str = Form(...),
    hypothesis_text: str = Form(...),
    baseline_methods: str = Form(""),
    metrics: str = Form(""),
    estimated_cost: str = Form("low"),
    estimated_runtime: str = Form("medium"),
    db: Session = Depends(get_db),
):
    data = ExperimentCardUpdate(
        name=name,
        objective=objective,
        hypothesis_text=hypothesis_text,
        baseline_methods=_split_csv(baseline_methods),
        metrics=_split_csv(metrics),
        estimated_cost=estimated_cost,
        estimated_runtime=estimated_runtime,
    )
    experiment_svc.update(db, experiment_id, data)
    return RedirectResponse(
        url=f"/ui/goals/{goal_id}/experiments/{experiment_id}?saved=true",
        status_code=303,
    )


# --- Read-only P1 views (CS-UI-005, 006, 007) ---


@router.get("/goals/{goal_id}/validation", response_class=HTMLResponse)
def validation_page(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    result = validation_svc.list_results(db, goal_id)
    experiments, _ = experiment_svc.list_experiments(db, goal_id, limit=200)
    execution = []
    for exp in experiments:
        bundles, _ = result_bundle_svc.list_bundles(db, exp.id)
        aggregation = _try_get_aggregation(db, exp.id)
        if bundles or aggregation:
            execution.append(
                {"experiment": exp, "bundles": bundles, "aggregation": aggregation}
            )
    return templates.TemplateResponse(
        request,
        "validation.html",
        {
            "goal": goal,
            "results": result.items,
            "total": result.total,
            "execution": execution,
            "score_update_on_partial": settings.score_update_on_partial,
        },
    )


@router.get("/goals/{goal_id}/devices", response_class=HTMLResponse)
def devices_page(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    result = device_svc.list_devices(db, goal_id, limit=200)
    return templates.TemplateResponse(
        request,
        "devices.html",
        {"goal": goal, "devices": result.items, "total": result.total},
    )


@router.get("/goals/{goal_id}/roadmap", response_class=HTMLResponse)
def roadmap_page(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    result = roadmap_svc.get_roadmap(db, goal_id, limit=200)
    return templates.TemplateResponse(
        request,
        "roadmap.html",
        {"goal": goal, "items": result.items, "total": result.total},
    )


@router.get("/goals/{goal_id}/evaluation", response_class=HTMLResponse)
def evaluation_page(request: Request, goal_id: str, db: Session = Depends(get_db)):
    try:
        goal = goal_svc.get(db, goal_id)
        report = evaluation_svc.get_report(db, goal_id)
    except HTTPException as exc:
        return _error(request, exc)
    return templates.TemplateResponse(
        request, "evaluation.html", {"goal": goal, "report": report}
    )


def _try_get_scores(db: Session, approach_id: str):
    try:
        return score_svc.get_scores(db, approach_id)
    except HTTPException:
        return None


def _try_get_aggregation(db: Session, experiment_id: str):
    try:
        return result_bundle_svc.get_aggregation(db, experiment_id)
    except HTTPException:
        return None
