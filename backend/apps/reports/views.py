from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.models import Member


def report_index(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/report_index.html")


def _render_report_form(
    request: HttpRequest,
    *,
    dept_code: str,
    title: str,
    leader_label: str,
    location_label: str,
    location_value: str = "",
    members=None,
) -> HttpResponse:
    if members is None:
        members = []
    return render(
        request,
        "reports/report_form.html",
        {
            "dept_code": dept_code,
            "title": title,
            "leader_label": leader_label,
            "location_label": location_label,
            "location_value": location_value,
            "members": members,
        },
    )


def _members_for_department(department_code: str):
    return Member.objects.filter(
        department_links__department__code=department_code
    ).distinct()


def report_un(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="UN",
        title="UN 報告フォーム（責任者まとめ報告）",
        leader_label="UN責任者（ログインユーザー）",
        location_label="現場名",
        members=_members_for_department("UN"),
    )


def report_wv(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="WV",
        title="WV 報告フォーム（責任者まとめ報告）",
        leader_label="WV責任者（ログインユーザー）",
        location_label="現場名",
        members=_members_for_department("WV"),
    )


def report_style1(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="Style1",
        title="Style1 報告フォーム（責任者まとめ報告）",
        leader_label="Style1責任者（ログインユーザー）",
        location_label="店舗",
        location_value="南町田",
        members=_members_for_department("STYLE1"),
    )


def report_style2(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="Style2",
        title="Style2 報告フォーム（責任者まとめ報告）",
        leader_label="Style2責任者（ログインユーザー）",
        location_label="店舗",
        location_value="港北",
        members=_members_for_department("STYLE2"),
    )
