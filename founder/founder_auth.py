from functools import wraps
FOUNDER_IDS = ["your_founder_id_here"]
def founder_only(func):
    @wraps(func)
    def wrapper(user, *args, **kwargs):
        if user.id not in FOUNDER_IDS:
            raise PermissionError("Founder only")
        return func(user, *args, **kwargs)
    return wrapper
@founder_only
def founder_dashboard(user):
    return {"message": "Founder view: trial, active, expired, suspended"}
