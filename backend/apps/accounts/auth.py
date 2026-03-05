from functools import wraps

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

ROLE_ADMIN = "admin"
ROLE_REPORT = "report"
SESSION_ROLE_KEY = "role"


def resolve_request_role(request: HttpRequest) -> str | None:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        role = ROLE_ADMIN if (user.is_staff or user.is_superuser) else ROLE_REPORT
        if request.session.get(SESSION_ROLE_KEY) != role:
            request.session[SESSION_ROLE_KEY] = role
        return role
    return request.session.get(SESSION_ROLE_KEY)


def require_roles(*allowed_roles: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            role = resolve_request_role(request)
            if role not in allowed_roles:
                return redirect("home")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
