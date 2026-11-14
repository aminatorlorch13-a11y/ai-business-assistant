from pathlib import Path
import shutil

path = Path("tests/test_integrations.py")
backup = path.with_name(path.name + ".pre_tamper_test.bak")

if not backup.exists():
    shutil.copy2(path, backup)

tests = path.read_text()
name = "test_tampered_secret_ciphertext_is_rejected"

if name not in tests:
    tests += '''

def test_tampered_secret_ciphertext_is_rejected(integration_setup):
    database, service, connection_id = integration_setup

    with database.transaction() as db:
        row = db.execute(
            "SELECT encrypted_payload FROM integration_secrets "
            "WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()

        tampered = bytearray(row["encrypted_payload"])
        tampered[-2] = tampered[-2] ^ 1

        db.execute(
            "UPDATE integration_secrets SET encrypted_payload = ? "
            "WHERE connection_id = ?",
            (bytes(tampered), connection_id),
        )

    with pytest.raises(RuntimeError, match="could not be authenticated"):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-a",
        )
'''
    path.write_text(tests)
    print("Tamper-detection test added.")
else:
    print("Tamper-detection test already exists.")
