class ActionExecutionError(RuntimeError):
    """Base execution-boundary error."""


class ActionPolicyDeniedError(PermissionError, ActionExecutionError):
    """Action is denied by policy."""


class ActionConfirmationRequiredError(PermissionError, ActionExecutionError):
    """Action requires explicit confirmation."""


class ActionOperationError(ActionExecutionError):
    """Authorized operation failed during execution."""
