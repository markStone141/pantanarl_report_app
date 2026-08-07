from django.contrib.auth import login as auth_login, logout as auth_logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .auth import ROLE_ADMIN, ROLE_REPORT, SESSION_ROLE_KEY, resolve_request_role
from .forms import LoginForm
from .services.authentication import authenticate_login


def _redirect_by_role(role: str):
    if role == ROLE_ADMIN:
        return redirect("dashboard_index")
    if role == ROLE_REPORT:
        return redirect("report_index")
    return redirect("home")


def home(request: HttpRequest) -> HttpResponse:
    current_role = resolve_request_role(request)
    if request.method == "GET" and current_role in {ROLE_ADMIN, ROLE_REPORT}:
        return _redirect_by_role(current_role)

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            login_id = form.cleaned_data["login_id"]
            password = form.cleaned_data["password"]

            result = authenticate_login(request, login_id=login_id, password=password)
            if result.is_success:
                auth_login(request, result.user)
                request.session[SESSION_ROLE_KEY] = result.role
                return _redirect_by_role(result.role)
            form.add_error(result.error_field, result.error_message)
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    request.session.pop(SESSION_ROLE_KEY, None)
    return redirect("home")
