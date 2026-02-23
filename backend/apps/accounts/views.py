from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .forms import LoginForm

REPORT_PASSWORD = "pn19450823"
ADMIN_PASSWORD = "pnadmin"


def home(request: HttpRequest) -> HttpResponse:
    route_map = {
        "admin": "dashboard_index",
        "un_report": "report_un",
        "wv_report": "report_wv",
        "style1_report": "report_style1",
        "style2_report": "report_style2",
        "un_ishii": "dashboard_index",
        "un_tanaka": "dashboard_index",
        "wv_sato": "dashboard_index",
        "style1_yamada": "dashboard_index",
        "style2_nakamura": "dashboard_index",
    }

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            login_id = form.cleaned_data["login_id"].strip().lower()
            password = form.cleaned_data["password"]
            route_name = route_map.get(login_id)
            if route_name:
                if login_id == "admin" and password != ADMIN_PASSWORD:
                    form.add_error("password", "管理者パスワードが違います。")
                    return render(request, "accounts/login.html", {"form": form})
                if login_id.endswith("_report") and password != REPORT_PASSWORD:
                    form.add_error("password", "報告用パスワードが違います。")
                    return render(request, "accounts/login.html", {"form": form})
                return redirect(route_name)
            form.add_error("login_id", "未登録のIDです。例: un_report / un_ishii / admin")
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})
