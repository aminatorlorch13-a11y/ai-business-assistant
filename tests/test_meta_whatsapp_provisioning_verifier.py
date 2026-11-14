import json
import unittest
from unittest.mock import patch, MagicMock

from app.whatsapp.provisioning_verifier import (
    MetaWhatsAppIdentityProvisioningVerifier,
)


class MetaWhatsAppProvisioningVerifierTests(unittest.TestCase):
    def setUp(self):
        self.verifier = MetaWhatsAppIdentityProvisioningVerifier(
            access_token="test-token",
            graph_api_version="v99.0",
        )

    @staticmethod
    def response(payload):
        result = MagicMock()
        result.status = 200
        result.read.return_value = json.dumps(payload).encode("utf-8")
        result.__enter__.return_value = result
        result.__exit__.return_value = False
        return result

    @patch("app.whatsapp.provisioning_verifier.urlopen")
    def test_accepts_phone_number_listed_under_claimed_waba(self, mocked):
        mocked.side_effect = [
            self.response({
                "id": "123456789",
                "display_phone_number": "+27123456789",
                "verified_name": "Example Business",
            }),
            self.response({
                "data": [{"id": "123456789"}],
            }),
        ]

        self.assertTrue(
            self.verifier.verify_assignment(
                business_id="business-1",
                provider="meta_whatsapp",
                assigned_identity="123456789",
                provider_reference="987654321",
            )
        )
        self.assertEqual(mocked.call_count, 2)

    @patch("app.whatsapp.provisioning_verifier.urlopen")
    def test_rejects_phone_number_not_listed_under_waba(self, mocked):
        mocked.side_effect = [
            self.response({"id": "123456789"}),
            self.response({"data": [{"id": "111111111"}]}),
        ]

        self.assertFalse(
            self.verifier.verify_assignment(
                business_id="business-1",
                provider="meta_whatsapp",
                assigned_identity="123456789",
                provider_reference="987654321",
            )
        )

    @patch("app.whatsapp.provisioning_verifier.urlopen")
    def test_rejects_phone_id_mismatch(self, mocked):
        mocked.return_value = self.response({"id": "different-id"})

        self.assertFalse(
            self.verifier.verify_assignment(
                business_id="business-1",
                provider="meta_whatsapp",
                assigned_identity="123456789",
                provider_reference="987654321",
            )
        )
        self.assertEqual(mocked.call_count, 1)

    @patch("app.whatsapp.provisioning_verifier.urlopen")
    def test_fails_closed_when_meta_is_unreachable(self, mocked):
        mocked.side_effect = OSError("network unavailable")

        self.assertFalse(
            self.verifier.verify_assignment(
                business_id="business-1",
                provider="meta_whatsapp",
                assigned_identity="123456789",
                provider_reference="987654321",
            )
        )

    @patch("app.whatsapp.provisioning_verifier.urlopen")
    def test_rejects_invalid_ids_without_network_access(self, mocked):
        self.assertFalse(
            self.verifier.verify_assignment(
                business_id="business-1",
                provider="meta_whatsapp",
                assigned_identity="not-a-phone-id",
                provider_reference="987654321",
            )
        )
        mocked.assert_not_called()

    @patch("app.whatsapp.provisioning_verifier.urlopen")
    def test_rejects_unexpected_provider(self, mocked):
        self.assertFalse(
            self.verifier.verify_assignment(
                business_id="business-1",
                provider="untrusted_provider",
                assigned_identity="123456789",
                provider_reference="987654321",
            )
        )
        mocked.assert_not_called()

    @patch("app.whatsapp.provisioning_verifier.urlopen")
    def test_rejects_untrusted_pagination_url(self, mocked):
        mocked.side_effect = [
            self.response({"id": "123456789"}),
            self.response({
                "data": [],
                "paging": {"next": "https://attacker.example/steal-token"},
            }),
        ]

        self.assertFalse(
            self.verifier.verify_assignment(
                business_id="business-1",
                provider="meta_whatsapp",
                assigned_identity="123456789",
                provider_reference="987654321",
            )
        )


if __name__ == "__main__":
    unittest.main()
