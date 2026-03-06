import os

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .auth import ROLE_ADMIN, ROLE_REPORT, SESSION_ROLE_KEY
from .forms import LoginForm

REPORT_USERNAME = os.getenv("REPORT_LOGIN_USERNAME", "report")
ADMIN_USERNAME = os.getenv("ADMIN_LOGIN_USERNAME", "admin")
REPORT_FIXED_PASSWORD = os.getenv("REPORT_FIXED_PASSWORD", "0823")


def _get_or_create_report_user():
    user_model = get_user_model()
    report_user, created = user_model.objects.get_or_create(
        username=REPORT_USERNAME,
        defaults={"is_active": True},
    )
    if not created and not report_user.is_active:
        report_user.is_active = True
        report_user.save(update_fields=["is_active"])
    return report_user


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
                form.add_error("password", "管理者パスワードが正しくありません。")
            elif login_id == ROLE_REPORT:
                authenticated_user = None
                if password == REPORT_FIXED_PASSWORD:
                    authenticated_user = _get_or_create_report_user()
                if not authenticated_user:
                    authenticated_user = authenticate(request, username=REPORT_USERNAME, password=password)
                if authenticated_user:
                    auth_login(request, authenticated_user)
                    request.session[SESSION_ROLE_KEY] = ROLE_REPORT
                    return redirect("report_index")
                form.add_error("password", "報告用パスワードが正しくありません。")
            else:
                form.add_error("login_id", "ログイン種別を選択してください。")
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    request.session.pop(SESSION_ROLE_KEY, None)
    return redirect("home")
