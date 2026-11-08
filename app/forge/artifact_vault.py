from __future__ import annotations

import json
from datetime import datetime, timezone

from app.forge.artifact_store import ForgeArtifactStore
from app.forge.verification import validate_candidate_verification_report
from app.forge.task_spec import ForgeTaskSpec
from app.forge.worker import ForgeExecutionResult


class ForgeArtifactVault:
    """Persists a validated Forge candidate in the tenant-scoped artifact store."""

    MEDIA_TYPE = "application/vnd.amination.forge-candidate+json"

    def __init__(self, artifact_store: ForgeArtifactStore) -> None:
        if not isinstance(artifact_store, ForgeArtifactStore):
            raise TypeError("artifact_store must be a ForgeArtifactStore.")
        self._store = artifact_store

    def __call__(
        self,
        spec: ForgeTaskSpec,
        result: ForgeExecutionResult,
    ) -> str:
        if not isinstance(spec, ForgeTaskSpec):
            raise TypeError("spec must be a ForgeTaskSpec.")
        if not isinstance(result, ForgeExecutionResult):
            raise TypeError("result must be a ForgeExecutionResult.")

        candidate = result.candidate
        expected_identity = {
            "business_id": spec.business_id,
            "project_id": spec.project_id,
            "job_id": spec.job_id,
        }

        for key, expected in expected_identity.items():
            if candidate.get(key) != expected:
                raise ValueError(
                    f"Candidate {key} does not match the immutable task spec."
                )

        if candidate.get("format") != "amination-forge-candidate-v1":
            raise ValueError("Unsupported Forge candidate format.")

        validate_candidate_verification_report(
            candidate.get("files"),
            candidate.get("verification"),
        )

        content = json.dumps(
            dict(candidate),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

        artifact = self._store.store(
            business_id=spec.business_id,
            project_id=spec.project_id,
            content=content,
            media_type=self.MEDIA_TYPE,
            created_at=datetime.now(timezone.utc),
        )

        return artifact.artifact_ref
