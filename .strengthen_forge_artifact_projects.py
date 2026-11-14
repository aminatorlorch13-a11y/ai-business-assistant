from pathlib import Path

p = Path("app/forge/artifact_store.py")
s = p.read_text()

needle = '''        digest = hashlib.sha256(content).hexdigest()
        self._write_blob(digest, content)
'''
replacement = '''        # Reject missing or archived projects before touching the filesystem.
        # Recheck inside the insert transaction to close the archive race.
        with self._database.connection() as connection:
            business = connection.execute(
                "SELECT 1 FROM businesses WHERE business_id = ?",
                (business_id,),
            ).fetchone()

            if business is None:
                raise ValueError("business_id does not reference an existing business.")

            project = connection.execute(
                """
                SELECT status
                FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()

            if project is None or project["status"] != "ACTIVE":
                raise ValueError(
                    "project_id must reference an existing active Forge project."
                )

        digest = hashlib.sha256(content).hexdigest()
        self._write_blob(digest, content)
'''
assert needle in s
s = s.replace(needle, replacement, 1)

needle = '''            if business is None:
                raise ValueError("business_id does not reference an existing business.")

            connection.execute(
                """
                INSERT INTO forge_artifacts (
'''
replacement = '''            if business is None:
                raise ValueError("business_id does not reference an existing business.")

            project = connection.execute(
                """
                SELECT status
                FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()

            if project is None or project["status"] != "ACTIVE":
                raise ValueError(
                    "project_id must reference an existing active Forge project."
                )

            connection.execute(
                """
                INSERT INTO forge_artifacts (
'''
assert needle in s
s = s.replace(needle, replacement, 1)
p.write_text(s)

p = Path("tests/test_forge_artifact_store.py")
s = p.read_text()
s += '''


def test_missing_project_is_rejected_before_blob_publication(tmp_path):
    _, store = make_store(tmp_path)
    root = tmp_path / "private-artifacts"

    with pytest.raises(ValueError, match="existing active Forge project"):
        store.store(
            "business-1",
            "missing-project",
            b"must not be published",
            "text/plain",
        )

    assert list(root.iterdir()) == []


def test_archived_project_cannot_receive_new_artifacts(tmp_path):
    database, store = make_store(tmp_path)
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE forge_projects
            SET status = 'ARCHIVED'
            WHERE business_id = ? AND project_id = ?
            """,
            ("business-1", "project-1"),
        )

    root = tmp_path / "private-artifacts"
    with pytest.raises(ValueError, match="existing active Forge project"):
        store.store(
            "business-1",
            "project-1",
            b"archived project content",
            "text/plain",
        )

    assert list(root.iterdir()) == []
'''
p.write_text(s)

print("Active-project checks and regression tests added.")
