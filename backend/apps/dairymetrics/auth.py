from functools import wraps

from django.http import Http404
from django.shortcuts import redirect


def get_member_profile(user):
    if not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "member_profile", None)


def require_dairymetrics_member(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return redirect("dairymetrics_login")
        if user.is_staff:
            return view_func(request, *args, **kwargs)
        if not get_member_profile(user):
            raise Http404()
        return view_func(request, *args, **kwargs)

    return wrapper


def require_dairymetrics_admin(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return redirect("dairymetrics_login")
        if not user.is_staff:
            raise Http404()
        return view_func(request, *args, **kwargs)

    return wrapper
