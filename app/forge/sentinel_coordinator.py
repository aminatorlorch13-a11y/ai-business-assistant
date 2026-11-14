from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.forge.artifact_store import (
    ArtifactIntegrityError,
    ForgeArtifactStore,
)
from app.forge.sentinel_guards import (
    ForgeSentinelAssessmentService,
)
from app.forge.sentinel_store import ForgeSentinelStore


_ARTIFACT_REF = re.compile(r"^forge-artifact://([0-9a-f]{32})$")
_CANDIDATE_MEDIA_TYPE = "application/vnd.amination.forge-candidate+json"
_MAX_CANDIDATE_BYTES = 3 * 1024 * 1024


class ForgeSentinelCoordinatorError(RuntimeError):
    """A vaulted candidate could not be safely assessed."""


class ForgeSentinelCoordinator:
    """Coordinates trusted artifact verification, Sentinel assessment and persistence."""

    def __init__(
        self,
        *,
        artifact_store: ForgeArtifactStore,
        assessment_service: ForgeSentinelAssessmentService,
        sentinel_store: ForgeSentinelStore,
    ) -> None:
        if not isinstance(artifact_store, ForgeArtifactStore):
            raise TypeError("artifact_store must be a ForgeArtifactStore.")
        if not isinstance(
            assessment_service, ForgeSentinelAssessmentService
        ):
            raise TypeError(
                "assessment_service must be a ForgeSentinelAssessmentService."
            )
        if not isinstance(sentinel_store, ForgeSentinelStore):
            raise TypeError("sentinel_store must be a ForgeSentinelStore.")

        self._artifacts = artifact_store
        self._assessment_service = assessment_service
        self._sentinel_store = sentinel_store

    def _read_verified_candidate(
        self,
        *,
        artifact_id: str,
        business_id: str,
        project_id: str,
        job_id: str,
    ) -> bytes:
        metadata = self._artifacts.get_metadata(
            artifact_id,
            business_id,
            project_id,
        )
        if metadata is None:
            raise ForgeSentinelCoordinatorError(
                "The candidate artifact does not exist in this scope."
            )

        if metadata.media_type != _CANDIDATE_MEDIA_TYPE:
            raise ForgeSentinelCoordinatorError(
                "The artifact is not a Forge candidate."
            )

        if metadata.size_bytes > _MAX_CANDIDATE_BYTES:
            raise ForgeSentinelCoordinatorError(
                "The candidate exceeds the Sentinel assessment size limit."
            )

        content = self._artifacts.read(
            artifact_id,
            business_id,
            project_id,
        )
        if content is None:
            raise ForgeSentinelCoordinatorError(
                "The candidate artifact could not be read."
            )

        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != metadata.sha256:
            raise ArtifactIntegrityError(
                "Candidate bytes do not match their stored digest."
            )

        try:
            candidate = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ForgeSentinelCoordinatorError(
                "The candidate artifact is not valid UTF-8 JSON."
            ) from exc

        if not isinstance(candidate, dict):
            raise ForgeSentinelCoordinatorError(
                "The candidate artifact must contain a JSON object."
            )

        expected = {
            "format": "amination-forge-candidate-v1",
            "business_id": business_id,
            "project_id": project_id,
            "job_id": job_id,
        }
        for key, value in expected.items():
            if candidate.get(key) != value:
                raise ForgeSentinelCoordinatorError(
                    f"Candidate {key} does not match the requested scope."
                )

        return content

    def assess(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
        artifact_reference: str,
    ) -> dict[str, Any]:
        values = (business_id, project_id, job_id)
        if any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 128
            for value in values
        ):
            raise ValueError("A valid business, project and job scope is required.")

        if not isinstance(artifact_reference, str):
            raise TypeError("artifact_reference must be a string.")

        match = _ARTIFACT_REF.fullmatch(artifact_reference)
        if match is None:
            raise ForgeSentinelCoordinatorError(
                "The candidate artifact reference is invalid."
            )

        artifact_id = match.group(1)

        def trusted_reader() -> bytes:
            return self._read_verified_candidate(
                artifact_id=artifact_id,
                business_id=business_id,
                project_id=project_id,
                job_id=job_id,
            )

        try:
            assessment = self._assessment_service.assess(
                artifact_ref=artifact_reference,
                candidate_reader=trusted_reader,
            )
            assessment_id = self._sentinel_store.record(
                business_id=business_id,
                project_id=project_id,
                job_id=job_id,
                assessment=assessment,
            )
        except Exception as exc:
            raise ForgeSentinelCoordinatorError(
                "Sentinel assessment or persistence failed closed."
            ) from exc

        return {
            "assessment_id": assessment_id,
            "artifact_reference": artifact_reference,
            "candidate_sha256": assessment.candidate_sha256,
            "status": assessment.status.value,
            "blocked_at_guard": assessment.blocked_at_guard,
            "results": [
                {
                    "guard_id": result.guard_id,
                    "verdict": result.verdict.value,
                    "implementation_id": result.implementation_id,
                    "findings": list(result.findings),
                }
                for result in assessment.results
            ],
        }


    def require_approved(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
        artifact_reference: str,
    ) -> dict[str, Any]:
        """Require the latest persisted assessment to approve this exact artifact."""
        latest = self._sentinel_store.latest_for_artifact(
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
            artifact_ref=artifact_reference,
        )
        if not isinstance(latest, dict):
            raise ForgeSentinelCoordinatorError(
                "No persisted Sentinel assessment exists for this Forge job."
            )

        if latest.get("artifact_ref") != artifact_reference:
            raise ForgeSentinelCoordinatorError(
                "The latest Sentinel assessment does not match the current artifact."
            )

        match = _ARTIFACT_REF.fullmatch(artifact_reference)
        if match is None:
            raise ForgeSentinelCoordinatorError(
                "The current Forge artifact reference is invalid."
            )

        content = self._read_verified_candidate(
            artifact_id=match.group(1),
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
        )
        digest = hashlib.sha256(content).hexdigest()

        if latest.get("candidate_sha256") != digest:
            raise ForgeSentinelCoordinatorError(
                "The latest Sentinel assessment digest does not match the current artifact."
            )

        expected_guard_ids = (
            "sentinel-guard-1",
            "sentinel-guard-2",
            "sentinel-guard-3",
            "sentinel-guard-4",
            "sentinel-guard-5",
        )
        results = latest.get("results")
        if (
            latest.get("status") != "ready_for_user_acceptance"
            or not isinstance(results, list)
            or len(results) != len(expected_guard_ids)
        ):
            raise ForgeSentinelCoordinatorError(
                "The current artifact has not passed all five Sentinel Guards."
            )

        for expected_id, result in zip(expected_guard_ids, results):
            if (
                not isinstance(result, dict)
                or result.get("guard_id") != expected_id
                or result.get("verdict") != "pass"
                or result.get("artifact_ref") != artifact_reference
                or result.get("candidate_sha256") != digest
            ):
                raise ForgeSentinelCoordinatorError(
                    "The persisted Sentinel results are incomplete or inconsistent."
                )

        return latest
