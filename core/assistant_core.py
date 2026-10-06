class AssistantCore:
    def __init__(self):
        self.history = {}
    def resolve_reference(self, message: str, business_id: str):
        hist = self.history.get(business_id, [])
        if "that" in message.lower() and hist:
            return hist[-1]
        return None
    def process(self, message: str, context):
        from core.tenant import enforce_tenant
        enforce_tenant(context.business_id, context)
        self.history.setdefault(context.business_id, []).append(message)
        ref = self.resolve_reference(message, context.business_id)
        return {"intent": "understood", "resolved_ref": ref}
