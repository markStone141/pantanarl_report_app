import os

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .auth import ROLE_ADMIN, ROLE_REPORT, SESSION_ROLE_KEY
from .forms import LoginForm

REPORT_PASSWORD = "0823"
ADMIN_PASSWORD = "pnadmin"
REPORT_USERNAME = os.getenv("REPORT_LOGIN_USERNAME", "report")
ADMIN_USERNAME = os.getenv("ADMIN_LOGIN_USERNAME", "admin")


def _redirect_by_role(role: str):
    if role == ROLE_ADMIN:
        return redirect("dashboard_index")
    if role == ROLE_REPORT:
        return redirect("report_index")
    return redirect("home")


def home(request: HttpRequest) -> HttpResponse:
    current_role = request.session.get(SESSION_ROLE_KEY)
    if request.method == "GET" and current_role in {ROLE_ADMIN, ROLE_REPORT}:
        return _redirect_by_role(current_role)

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            login_id = form.cleaned_data["login_id"]
            password = form.cleaned_data["password"]

            if login_id == ROLE_ADMIN:
                authenticated_user = authenticate(request, username=ADMIN_USERNAME, password=password)
                if authenticated_user:
                    auth_login(request, authenticated_user)
                    request.session[SESSION_ROLE_KEY] = ROLE_ADMIN
                    return redirect("dashboard_index")
                if password != ADMIN_PASSWORD:
                    form.add_error("password", "管理者パスワードが違います。")
                else:
                    request.session[SESSION_ROLE_KEY] = ROLE_ADMIN
                    return redirect("dashboard_index")
            elif login_id == ROLE_REPORT:
                authenticated_user = authenticate(request, username=REPORT_USERNAME, password=password)
                if authenticated_user:
                    auth_login(request, authenticated_user)
                    request.session[SESSION_ROLE_KEY] = ROLE_REPORT
                    return redirect("report_index")
                if password != REPORT_PASSWORD:
                    form.add_error("password", "報告用パスワードが違います。")
                else:
                    request.session[SESSION_ROLE_KEY] = ROLE_REPORT
                    return redirect("report_index")
            else:
                form.add_error("login_id", "ログイン種別を選択してください。")
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    request.session.pop(SESSION_ROLE_KEY, None)
    return redirect("home")
