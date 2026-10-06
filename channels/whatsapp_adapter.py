import hmac
from core.assistant_core import AssistantCore
from core.tenant import TenantContext
core = AssistantCore()
def verify_signature(payload: bytes, signature: str, secret: str):
    expected = hmac.new(secret.encode(), payload, b"sha256").hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid signature")
    return True
def handle_whatsapp(phone: str, text: str, business_id: str, context: TenantContext):
    return core.process(text, context)
