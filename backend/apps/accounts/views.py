from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .auth import ROLE_ADMIN, ROLE_REPORT, SESSION_ROLE_KEY
from .forms import LoginForm

REPORT_PASSWORD = "pn19450823"
ADMIN_PASSWORD = "pnadmin"


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
            login_id = form.cleaned_data["login_id"].strip().lower()
            password = form.cleaned_data["password"]

            if login_id == ROLE_ADMIN:
                if password != ADMIN_PASSWORD:
                    form.add_error("password", "管理者パスワードが違います。")
                else:
                    request.session[SESSION_ROLE_KEY] = ROLE_ADMIN
                    return redirect("dashboard_index")
            elif login_id == ROLE_REPORT:
                if password != REPORT_PASSWORD:
                    form.add_error("password", "報告用パスワードが違います。")
                else:
                    request.session[SESSION_ROLE_KEY] = ROLE_REPORT
                    return redirect("report_index")
            else:
                form.add_error("login_id", "IDは admin または report を入力してください。")
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request: HttpRequest) -> HttpResponse:
    request.session.pop(SESSION_ROLE_KEY, None)
    return redirect("home")
