import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app.owner.models import OwnerLifestylePreferences, RoutineSuggestion, ROUTINE_FIELDS
from app.persistence.database import SQLiteDatabase


class SQLiteOwnerLifestyleRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def from_row(row):
        data = dict(row)
        data["preferred_channels"] = tuple(json.loads(data["preferred_channels"]))
        data["briefing_enabled"] = bool(data["briefing_enabled"])
        data["critical_alerts_during_quiet"] = bool(data["critical_alerts_during_quiet"])
        return OwnerLifestylePreferences(**data)

    def get(self, business_id, user_id):
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM owner_lifestyle_preferences WHERE business_id=? AND user_id=?",
                (business_id, user_id),
            ).fetchone()
        return self.from_row(row) if row else None

    def save(self, p):
        if not isinstance(p, OwnerLifestylePreferences):
            raise TypeError("Expected OwnerLifestylePreferences.")
        now = self.now()
        with self.database.connection() as conn:
            conn.execute("""
                INSERT INTO owner_lifestyle_preferences (
                    business_id,user_id,timezone,wake_time,sleep_time,work_start,work_end,
                    quiet_start,quiet_end,briefing_enabled,briefing_time,initiative_level,
                    personality,preferred_channels,critical_alerts_during_quiet,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(business_id,user_id) DO UPDATE SET
                    timezone=excluded.timezone,wake_time=excluded.wake_time,
                    sleep_time=excluded.sleep_time,work_start=excluded.work_start,
                    work_end=excluded.work_end,quiet_start=excluded.quiet_start,
                    quiet_end=excluded.quiet_end,briefing_enabled=excluded.briefing_enabled,
                    briefing_time=excluded.briefing_time,initiative_level=excluded.initiative_level,
                    personality=excluded.personality,preferred_channels=excluded.preferred_channels,
                    critical_alerts_during_quiet=excluded.critical_alerts_during_quiet,
                    updated_at=excluded.updated_at
            """, (
                p.business_id,p.user_id,p.timezone,p.wake_time,p.sleep_time,p.work_start,
                p.work_end,p.quiet_start,p.quiet_end,int(p.briefing_enabled),p.briefing_time,
                p.initiative_level,p.personality,json.dumps(p.preferred_channels),
                int(p.critical_alerts_during_quiet),p.created_at or now,now,
            ))
        return self.get(p.business_id, p.user_id)

    def record_observation(self, business_id, user_id, field_name, proposed_value):
        from app.owner.models import validate_time
        if field_name not in ROUTINE_FIELDS:
            raise ValueError("Unsupported routine field.")
        validate_time(proposed_value, field_name)
        now = self.now()
        with self.database.connection() as conn:
            conn.execute("""
                INSERT INTO owner_routine_suggestions (
                    suggestion_id,business_id,user_id,field_name,proposed_value,
                    observation_count,first_observed_at,last_observed_at,status
                ) VALUES (?,?,?,?,?,1,?,?,'pending')
                ON CONFLICT(business_id,user_id,field_name,proposed_value)
                DO UPDATE SET observation_count=observation_count+1,
                    last_observed_at=excluded.last_observed_at
                WHERE status='pending'
            """, (str(uuid.uuid4()),business_id,user_id,field_name,proposed_value,now,now))
            row = conn.execute("""
                SELECT * FROM owner_routine_suggestions
                WHERE business_id=? AND user_id=? AND field_name=? AND proposed_value=?
            """, (business_id,user_id,field_name,proposed_value)).fetchone()
        return RoutineSuggestion(**dict(row))

    def list_suggestions(self, business_id, user_id, status="pending"):
        if status not in {"pending", "accepted", "rejected"}:
            raise ValueError("Invalid status.")
        with self.database.connection() as conn:
            rows = conn.execute("""
                SELECT * FROM owner_routine_suggestions
                WHERE business_id=? AND user_id=? AND status=?
                ORDER BY last_observed_at DESC
            """, (business_id,user_id,status)).fetchall()
        return [RoutineSuggestion(**dict(row)) for row in rows]

    def resolve_suggestion(self, business_id, user_id, suggestion_id, accept):
        if type(accept) is not bool:
            raise ValueError("accept must be boolean.")
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("""
                    SELECT * FROM owner_routine_suggestions
                    WHERE suggestion_id=? AND business_id=? AND user_id=?
                """, (suggestion_id,business_id,user_id)).fetchone()
                if row is None:
                    raise LookupError("Suggestion not found.")
                if row["status"] != "pending":
                    raise ValueError("Suggestion already resolved.")
                current_row = conn.execute("""
                    SELECT * FROM owner_lifestyle_preferences
                    WHERE business_id=? AND user_id=?
                """, (business_id,user_id)).fetchone()
                current = self.from_row(current_row) if current_row else OwnerLifestylePreferences(
                    business_id=business_id,user_id=user_id
                )
                if accept:
                    from dataclasses import replace
                    current = replace(current, **{row["field_name"]: row["proposed_value"]})
                    now = self.now()
                    conn.execute("""
                        UPDATE owner_lifestyle_preferences SET
                            timezone=?,wake_time=?,sleep_time=?,work_start=?,work_end=?,
                            quiet_start=?,quiet_end=?,briefing_enabled=?,briefing_time=?,
                            initiative_level=?,personality=?,preferred_channels=?,
                            critical_alerts_during_quiet=?,updated_at=?
                        WHERE business_id=? AND user_id=?
                    """, (
                        current.timezone,current.wake_time,current.sleep_time,current.work_start,
                        current.work_end,current.quiet_start,current.quiet_end,
                        int(current.briefing_enabled),current.briefing_time,current.initiative_level,
                        current.personality,json.dumps(current.preferred_channels),
                        int(current.critical_alerts_during_quiet),now,business_id,user_id,
                    ))
                conn.execute("""
                    UPDATE owner_routine_suggestions SET status=?,resolved_at=?
                    WHERE suggestion_id=? AND status='pending'
                """, ("accepted" if accept else "rejected",self.now(),suggestion_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get(business_id, user_id)
