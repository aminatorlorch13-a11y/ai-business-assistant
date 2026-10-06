from __future__ import annotations

from app.assistant.capability import Capability
from app.persistence.database import SQLiteDatabase


class SQLiteCapabilityEntitlementRepository:
    """Durable application-owned source of business capability entitlements.

    Commercial lifecycle state is deliberately not consulted here.

    Configuration and individual grants are separate so an explicitly
    configured business with zero capabilities remains distinct from an
    unconfigured business.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def configure(
        self,
        business_id: str,
        capabilities: frozenset[Capability],
    ) -> None:
        business_id = _validate_business_id(business_id)
        _validate_capabilities(capabilities)

        with self._database.transaction() as connection:
            connection.execute(
                '''
                INSERT INTO business_capability_entitlements(
                    business_id,
                    configured_at
                )
                VALUES (?, datetime('now'))
                ON CONFLICT(business_id) DO NOTHING
                ''',
                (business_id,),
            )

            connection.execute(
                '''
                DELETE FROM business_capability_grants
                WHERE business_id = ?
                ''',
                (business_id,),
            )

            for capability in capabilities:
                connection.execute(
                    '''
                    INSERT INTO business_capability_grants(
                        business_id,
                        capability
                    )
                    VALUES (?, ?)
                    ''',
                    (business_id, capability.value),
                )

    def is_configured(self, business_id: str) -> bool:
        business_id = _validate_business_id(business_id)

        with self._database.connection() as connection:
            row = connection.execute(
                '''
                SELECT 1
                FROM business_capability_entitlements
                WHERE business_id = ?
                ''',
                (business_id,),
            ).fetchone()

        return row is not None

    def get(
        self,
        business_id: str,
    ) -> frozenset[Capability] | None:
        business_id = _validate_business_id(business_id)

        with self._database.connection() as connection:
            configured = connection.execute(
                '''
                SELECT 1
                FROM business_capability_entitlements
                WHERE business_id = ?
                ''',
                (business_id,),
            ).fetchone()

            if configured is None:
                return None

            rows = connection.execute(
                '''
                SELECT capability
                FROM business_capability_grants
                WHERE business_id = ?
                ORDER BY capability
                ''',
                (business_id,),
            ).fetchall()

        try:
            return frozenset(
                Capability(row["capability"])
                for row in rows
            )
        except ValueError as exc:
            raise RuntimeError(
                "Stored capability entitlement is invalid."
            ) from exc

    def grant(
        self,
        business_id: str,
        capability: Capability,
    ) -> None:
        business_id = _validate_business_id(business_id)

        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability.")

        with self._database.transaction() as connection:
            configured = connection.execute(
                '''
                SELECT 1
                FROM business_capability_entitlements
                WHERE business_id = ?
                ''',
                (business_id,),
            ).fetchone()

            if configured is None:
                raise ValueError(
                    "Business must be explicitly configured before "
                    "capabilities can be granted."
                )

            connection.execute(
                '''
                INSERT INTO business_capability_grants(
                    business_id,
                    capability
                )
                VALUES (?, ?)
                ON CONFLICT(business_id, capability) DO NOTHING
                ''',
                (business_id, capability.value),
            )

    def revoke(
        self,
        business_id: str,
        capability: Capability,
    ) -> bool:
        business_id = _validate_business_id(business_id)

        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability.")

        with self._database.transaction() as connection:
            cursor = connection.execute(
                '''
                DELETE FROM business_capability_grants
                WHERE business_id = ?
                  AND capability = ?
                ''',
                (business_id, capability.value),
            )

        return cursor.rowcount == 1


def _validate_business_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("business_id must be a string.")

    value = value.strip()

    if not value:
        raise ValueError("business_id must be a non-empty string.")

    if len(value) > 128:
        raise ValueError(
            "business_id exceeds the maximum allowed length."
        )

    return value


def _validate_capabilities(value: object) -> None:
    if not isinstance(value, frozenset):
        raise TypeError("capabilities must be a frozenset.")

    for capability in value:
        if not isinstance(capability, Capability):
            raise TypeError(
                "capabilities must contain only Capability values."
            )
