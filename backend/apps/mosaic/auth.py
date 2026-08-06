from functools import wraps

from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode


def require_mosaic_login(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs) -> HttpResponse:
        if getattr(request.user, "is_authenticated", False):
            return view_func(request, *args, **kwargs)
        next_url = request.get_full_path()
        query = urlencode({"next": next_url}) if next_url else ""
        login_url = reverse("mosaic_login")
        return redirect(f"{login_url}?{query}" if query else login_url)

    return wrapper
