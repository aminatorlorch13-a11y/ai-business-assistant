from pathlib import Path
import shutil

path = Path("tests/test_integrations.py")
backup = path.with_name(path.name + ".pre_tenant_isolation.bak")

if not backup.exists():
    shutil.copy2(path, backup)

text = path.read_text()
name = "test_same_business_other_user_cannot_read_or_revoke_connection"

if name not in text:
    text += '''

def test_same_business_other_user_cannot_read_or_revoke_connection(integration_setup):
    database, service, connection_id = integration_setup

    with pytest.raises(PermissionError):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-b",
        )

    with pytest.raises(PermissionError):
        service.revoke(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-b",
        )

    assert service.has_permission(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
        scope="email.read",
    )
    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    ) == {"access_token": "secret-token-value"}

    with database.connection() as db:
        status = db.execute(
            "SELECT status FROM integration_connections WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()["status"]

    assert status == "active"
'''
    path.write_text(text)
    print("Tenant-isolation test added.")
else:
    print("Test already exists; no changes made.")
