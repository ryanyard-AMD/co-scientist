import pytest
from fastapi import HTTPException

from coscientist.schemas.goal import (
    DeviceConstraints,
    GoalCreate,
    GoalStatusEnum,
    GoalUpdate,
    SuccessCriterion,
)
from coscientist.services import goal as svc

_CRITERIA = [SuccessCriterion(name="contrast", operator=">=", target=20.0, unit="dB")]


def _make_goal(db, name="Test Goal"):
    return svc.create(
        db,
        GoalCreate(
            name=name,
            target_application="personal_sound_zones",
            success_criteria=_CRITERIA,
        ),
    )


def test_create_sets_workspace_id_equal_to_id(db_session):
    g = _make_goal(db_session)
    assert g.workspace_id == g.id


def test_create_default_status_is_draft(db_session):
    g = _make_goal(db_session)
    assert g.status == GoalStatusEnum.draft


def test_get_returns_goal(db_session):
    g = _make_goal(db_session)
    fetched = svc.get(db_session, g.id)
    assert fetched.id == g.id


def test_get_raises_404_for_unknown_id(db_session):
    with pytest.raises(HTTPException) as exc:
        svc.get(db_session, "does-not-exist")
    assert exc.value.status_code == 404


def test_list_returns_all(db_session):
    _make_goal(db_session, "A")
    _make_goal(db_session, "B")
    items, total = svc.list_goals(db_session)
    assert total == 2
    assert len(items) == 2


def test_list_filter_by_status(db_session):
    g = _make_goal(db_session)
    svc.transition(db_session, g.id, GoalStatusEnum.active)
    items, total = svc.list_goals(db_session, status=GoalStatusEnum.active)
    assert total == 1
    items, total = svc.list_goals(db_session, status=GoalStatusEnum.draft)
    assert total == 0


def test_update_name(db_session):
    g = _make_goal(db_session)
    updated = svc.update(db_session, g.id, GoalUpdate(name="New Name"))
    assert updated.name == "New Name"


def test_transition_draft_to_active(db_session):
    g = _make_goal(db_session)
    result = svc.transition(db_session, g.id, GoalStatusEnum.active)
    assert result.status == GoalStatusEnum.active


def test_transition_active_to_archived(db_session):
    g = _make_goal(db_session)
    svc.transition(db_session, g.id, GoalStatusEnum.active)
    result = svc.transition(db_session, g.id, GoalStatusEnum.archived)
    assert result.status == GoalStatusEnum.archived


def test_transition_archived_is_terminal(db_session):
    g = _make_goal(db_session)
    svc.transition(db_session, g.id, GoalStatusEnum.archived)
    with pytest.raises(HTTPException) as exc:
        svc.transition(db_session, g.id, GoalStatusEnum.active)
    assert exc.value.status_code == 422


def test_transition_same_status_raises(db_session):
    g = _make_goal(db_session)
    with pytest.raises(HTTPException) as exc:
        svc.transition(db_session, g.id, GoalStatusEnum.draft)
    assert exc.value.status_code == 422


def test_delete_draft(db_session):
    g = _make_goal(db_session)
    svc.delete(db_session, g.id)
    with pytest.raises(HTTPException) as exc:
        svc.get(db_session, g.id)
    assert exc.value.status_code == 404


def test_delete_active_raises_409(db_session):
    g = _make_goal(db_session)
    svc.transition(db_session, g.id, GoalStatusEnum.active)
    with pytest.raises(HTTPException) as exc:
        svc.delete(db_session, g.id)
    assert exc.value.status_code == 409
