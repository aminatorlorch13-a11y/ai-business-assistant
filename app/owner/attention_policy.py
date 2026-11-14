from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class AttentionDecision:
    action: str
    reason: str
    evaluated_at: str
    local_time: str
    quiet_hours_active: bool
    deliver_after: str | None = None


class OwnerAttentionPolicy:
    """Deterministic, preference-driven interruption policy."""

    SEVERITIES = {"critical", "important", "routine"}

    @staticmethod
    def _parse(value):
        return time.fromisoformat(value) if value else None

    @classmethod
    def _window_end(cls, current, start_value, end_value):
        start = cls._parse(start_value)
        end = cls._parse(end_value)

        if start is None or end is None or start == end:
            return None

        current_time = current.timetz().replace(tzinfo=None)

        if start < end:
            if start <= current_time < end:
                return datetime.combine(current.date(), end, current.tzinfo)
            return None

        # Overnight window, for example 22:00–06:00.
        if current_time >= start:
            return datetime.combine(
                current.date() + timedelta(days=1), end, current.tzinfo
            )
        if current_time < end:
            return datetime.combine(current.date(), end, current.tzinfo)
        return None

    @classmethod
    def _quiet_end(cls, preferences, current):
        windows = (
            (preferences.sleep_time, preferences.wake_time),
            (preferences.quiet_start, preferences.quiet_end),
        )
        cursor = current
        active = False

        # Advance through overlapping or directly adjoining quiet windows.
        for _ in range(4):
            ends = [
                end
                for start, finish in windows
                if (end := cls._window_end(cursor, start, finish)) is not None
            ]
            if not ends:
                break
            active = True
            cursor = max(ends)

        return (active, cursor if active else None)

    @staticmethod
    def _next_briefing(preferences, current):
        if not preferences.briefing_enabled:
            return None

        briefing = time.fromisoformat(preferences.briefing_time)
        candidate = datetime.combine(current.date(), briefing, current.tzinfo)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate

    @classmethod
    def evaluate(cls, preferences, severity, now=None):
        if severity not in cls.SEVERITIES:
            raise ValueError("Severity must be critical, important, or routine.")

        zone = ZoneInfo(preferences.timezone)
        now = now or datetime.now(zone)

        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("Evaluation time must be timezone-aware.")

        local_now = now.astimezone(zone)
        quiet, quiet_end = cls._quiet_end(preferences, local_now)

        def decision(action, reason, deliver_after=None):
            return AttentionDecision(
                action=action,
                reason=reason,
                evaluated_at=now.isoformat(),
                local_time=local_now.isoformat(),
                quiet_hours_active=quiet,
                deliver_after=(
                    deliver_after.isoformat() if deliver_after else None
                ),
            )

        if severity == "routine":
            briefing_at = cls._next_briefing(preferences, local_now)
            if briefing_at:
                return decision(
                    "briefing",
                    "Routine information is reserved for the owner's briefing.",
                    briefing_at,
                )
            return decision(
                "queue",
                "Briefings are disabled; retain this item for later review.",
            )

        if quiet:
            if severity == "critical" and preferences.critical_alerts_during_quiet:
                return decision(
                    "interrupt",
                    "Critical alert permitted by the owner's quiet-hours policy.",
                )

            return decision(
                "defer",
                "Owner is in a protected quiet or sleep period.",
                quiet_end,
            )

        if severity == "critical":
            return decision("interrupt", "Critical event; immediate attention required.")

        return decision("deliver", "Important event; outside protected quiet hours.")
