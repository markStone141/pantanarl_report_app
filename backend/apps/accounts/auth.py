from functools import wraps

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

ROLE_ADMIN = "admin"
ROLE_REPORT = "report"
SESSION_ROLE_KEY = "role"


def require_roles(*allowed_roles: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            role = request.session.get(SESSION_ROLE_KEY)
            if role not in allowed_roles:
                return redirect("home")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
