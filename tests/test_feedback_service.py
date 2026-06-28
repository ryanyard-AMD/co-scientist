import pytest
from fastapi import HTTPException

from conftest import GOAL_PAYLOAD
from coscientist.schemas.feedback import FeedbackCreate, FeedbackTargetEnum
from coscientist.schemas.goal import GoalCreate
from coscientist.services import feedback as svc
from coscientist.services import goal as goal_svc


def _make_goal(db):
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD)).id


def _fc(**overrides):
    data = dict(
        target_type=FeedbackTargetEnum.approach,
        target_id="approach-1",
        is_positive=True,
    )
    data.update(overrides)
    return FeedbackCreate(**data)


def test_create_persists_feedback(db_session):
    gid = _make_goal(db_session)
    resp = svc.create(db_session, gid, _fc(comment="useful", reviewer_id="alice"))
    assert resp.id
    assert resp.workspace_id == gid
    assert resp.target_type == FeedbackTargetEnum.approach
    assert resp.is_positive is True
    assert resp.comment == "useful"
    assert resp.reviewer_id == "alice"


def test_create_unknown_goal_404(db_session):
    with pytest.raises(HTTPException) as exc:
        svc.create(db_session, "nope", _fc())
    assert exc.value.status_code == 404


def test_list_returns_all_for_goal(db_session):
    gid = _make_goal(db_session)
    svc.create(db_session, gid, _fc(is_positive=True))
    svc.create(db_session, gid, _fc(is_positive=False))
    result = svc.list_feedback(db_session, gid)
    assert result.total == 2


def test_list_filters_by_target_type(db_session):
    gid = _make_goal(db_session)
    svc.create(db_session, gid, _fc(target_type=FeedbackTargetEnum.approach))
    svc.create(db_session, gid, _fc(target_type=FeedbackTargetEnum.experiment, target_id="exp-1"))
    result = svc.list_feedback(db_session, gid, target_type=FeedbackTargetEnum.experiment)
    assert result.total == 1
    assert result.items[0].target_type == FeedbackTargetEnum.experiment


def test_list_filters_by_target_id(db_session):
    gid = _make_goal(db_session)
    svc.create(db_session, gid, _fc(target_id="approach-1"))
    svc.create(db_session, gid, _fc(target_id="approach-2"))
    result = svc.list_feedback(db_session, gid, target_id="approach-2")
    assert result.total == 1
    assert result.items[0].target_id == "approach-2"


def test_satisfaction_counts(db_session):
    gid = _make_goal(db_session)
    svc.create(db_session, gid, _fc(is_positive=True))
    svc.create(db_session, gid, _fc(is_positive=True))
    svc.create(db_session, gid, _fc(is_positive=False))
    positive, total = svc.satisfaction_counts(db_session, gid)
    assert positive == 2
    assert total == 3


def test_satisfaction_counts_empty(db_session):
    gid = _make_goal(db_session)
    assert svc.satisfaction_counts(db_session, gid) == (0, 0)
