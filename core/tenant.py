from enum import Enum
from dataclasses import dataclass

class CommercialState(Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    def is_blocked(self):
        return self in [CommercialState.EXPIRED, CommercialState.SUSPENDED]

class CommercialEntitlementError(Exception): pass
class CrossTenantAttackError(Exception): pass

@dataclass
class TenantContext:
    business_id: str
    user_id: str
    commercial_state: CommercialState

def enforce_tenant(action_business_id: str, context: TenantContext):
    if context.commercial_state.is_blocked():
        raise CommercialEntitlementError(f"Business {context.business_id} is {context.commercial_state.value}")
    if action_business_id != context.business_id:
        raise CrossTenantAttackError(f"Cross-tenant: {action_business_id} vs {context.business_id}")
    return True
