import sys
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.governance import AgentActionLog
from coscientist.schemas.governance import AgentActionLogListResponse, AgentActionLogResponse


def _to_response(log: AgentActionLog) -> AgentActionLogResponse:
    return AgentActionLogResponse(
        id=log.id,
        workspace_id=log.workspace_id,
        service=log.service,
        action=log.action,
        model_used=log.model_used,
        prompt_tokens=log.prompt_tokens,
        completion_tokens=log.completion_tokens,
        elapsed_ms=log.elapsed_ms,
        response_summary=log.response_summary,
        error=log.error,
        created_at=log.created_at,
    )


def log_agent_call(
    db: Session,
    workspace_id: str,
    service: str,
    action: str,
    model_used: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    elapsed_ms: int | None = None,
    response_summary: str | None = None,
    error: str | None = None,
) -> None:
    try:
        row = AgentActionLog(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            service=service,
            action=action,
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=elapsed_ms,
            response_summary=response_summary,
            error=error,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()
    except Exception as exc:
        print(f"[governance] Failed to write agent action log: {exc}", file=sys.stderr)


def list_logs(
    db: Session,
    goal_id: str,
    service: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> AgentActionLogListResponse:
    stmt = (
        select(AgentActionLog)
        .where(AgentActionLog.workspace_id == goal_id)
        .order_by(AgentActionLog.created_at.desc())
    )
    if service is not None:
        stmt = stmt.where(AgentActionLog.service == service)

    all_logs = list(db.scalars(stmt))
    total = len(all_logs)
    page = all_logs[skip : skip + limit]
    return AgentActionLogListResponse(items=[_to_response(l) for l in page], total=total)


def get_log(db: Session, log_id: str, goal_id: str) -> AgentActionLogResponse:
    log = db.get(AgentActionLog, log_id)
    if log is None or log.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Agent action log {log_id!r} not found")
    return _to_response(log)
