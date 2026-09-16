from app.safety.enforcement import SafetyEnforcement


class AllowAllTestSafetyEnforcement(SafetyEnforcement):
    """Test-only pass-through safety boundary.

    Real SafetyEnforcement behavior is covered by the D5 safety suites.
    """

    def __init__(self):
        pass

    def require_execution_allowed(self, business_id):
        return None

    def require_capability_allowed(self, capability):
        return None

    def require_channel_allowed(self, channel):
        return None

    def require_integration_allowed(self, integration):
        return None
