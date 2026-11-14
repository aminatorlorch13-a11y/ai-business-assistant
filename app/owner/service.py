from dataclasses import replace

from app.owner.models import OwnerLifestylePreferences


class OwnerLifestyleService:
    EDITABLE_FIELDS = {
        "timezone","wake_time","sleep_time","work_start","work_end",
        "quiet_start","quiet_end","briefing_enabled","briefing_time",
        "initiative_level","personality","preferred_channels",
        "critical_alerts_during_quiet",
    }

    def __init__(self, repository, membership_repository):
        self.repository = repository
        self.memberships = membership_repository

    def identity(self, principal, business_id):
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id.strip():
            raise PermissionError("Authenticated user required.")
        if getattr(principal, "business_id", None) != business_id:
            raise PermissionError("Business context mismatch.")
        if self.memberships.get(user_id, business_id) is None:
            raise PermissionError("Business membership required.")
        return user_id

    def get_preferences(self, principal, business_id):
        user_id = self.identity(principal, business_id)
        current = self.repository.get(business_id, user_id)
        return current or self.repository.save(
            OwnerLifestylePreferences(business_id=business_id,user_id=user_id)
        )

    def update_preferences(self, principal, business_id, changes):
        user_id = self.identity(principal, business_id)
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Provide preference changes.")
        if set(changes) - self.EDITABLE_FIELDS:
            raise ValueError("Unsupported preference field.")
        if "preferred_channels" in changes and isinstance(changes["preferred_channels"], list):
            changes = {**changes, "preferred_channels": tuple(changes["preferred_channels"])}
        current = self.repository.get(business_id, user_id) or OwnerLifestylePreferences(
            business_id=business_id,user_id=user_id
        )
        return self.repository.save(replace(current, **changes))

    def observe_routine(self, principal, business_id, field_name, proposed_value):
        user_id = self.identity(principal, business_id)
        if self.repository.get(business_id, user_id) is None:
            self.repository.save(OwnerLifestylePreferences(
                business_id=business_id,user_id=user_id
            ))
        return self.repository.record_observation(
            business_id,user_id,field_name,proposed_value
        )

    def list_pending_suggestions(self, principal, business_id):
        user_id = self.identity(principal, business_id)
        return self.repository.list_suggestions(business_id,user_id)

    def resolve_suggestion(self, principal, business_id, suggestion_id, accept):
        user_id = self.identity(principal, business_id)
        return self.repository.resolve_suggestion(
            business_id,user_id,suggestion_id,accept
        )
