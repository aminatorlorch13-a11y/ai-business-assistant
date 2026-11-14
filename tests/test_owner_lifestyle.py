from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.owner.models import OwnerLifestylePreferences
from app.owner.service import OwnerLifestyleService


def make_service():
    repo = Mock()
    memberships = Mock()
    memberships.get.return_value = object()
    repo.get.return_value = OwnerLifestylePreferences("business-1","user-1")
    return OwnerLifestyleService(repo,memberships),repo,memberships


def principal():
    return SimpleNamespace(user_id="user-1",business_id="business-1")


def test_defaults():
    p = OwnerLifestylePreferences("business-1","user-1")
    assert p.personality == "natural"
    assert p.initiative_level == "balanced"
    assert p.briefing_enabled


def test_invalid_time():
    with pytest.raises(ValueError):
        OwnerLifestylePreferences("b","u",wake_time="25:90")


def test_invalid_timezone():
    with pytest.raises(ValueError):
        OwnerLifestylePreferences("b","u",timezone="Not/AZone")


def test_invalid_channel():
    with pytest.raises(ValueError):
        OwnerLifestylePreferences("b","u",preferred_channels=("unknown",))


def test_membership_required():
    service,repo,memberships = make_service()
    memberships.get.return_value = None
    with pytest.raises(PermissionError):
        service.get_preferences(principal(),"business-1")
    repo.get.assert_not_called()


def test_business_context_required():
    service,repo,_ = make_service()
    with pytest.raises(PermissionError):
        service.get_preferences(principal(),"other-business")
    repo.get.assert_not_called()


def test_unknown_update_rejected():
    service,repo,_ = make_service()
    with pytest.raises(ValueError):
        service.update_preferences(principal(),"business-1",{"user_id":"other"})
    repo.save.assert_not_called()


def test_update_preserves_defaults():
    service,repo,_ = make_service()
    updated = replace(repo.get.return_value,briefing_time="08:00")
    repo.save.return_value = updated
    result = service.update_preferences(
        principal(),"business-1",{"briefing_time":"08:00"}
    )
    assert result.briefing_time == "08:00"
    assert result.personality == "natural"


def test_observation_does_not_apply_automatically():
    service,repo,_ = make_service()
    service.observe_routine(principal(),"business-1","wake_time","06:00")
    repo.save.assert_not_called()
    repo.record_observation.assert_called_once()
