from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.models import Department, Member


def report_index(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/report_index.html")


def _render_report_form(
    request: HttpRequest,
    *,
    dept_code: str,
    title: str,
    location_label: str,
    location_value: str = "",
    members=None,
    default_reporter_id=None,
) -> HttpResponse:
    if members is None:
        members = []
    return render(
        request,
        "reports/report_form.html",
        {
            "dept_code": dept_code,
            "title": title,
            "location_label": location_label,
            "location_value": location_value,
            "members": members,
            "default_reporter_id": default_reporter_id,
        },
    )


def _members_for_department(department_code: str):
    return Member.objects.filter(
        department_links__department__code=department_code
    ).distinct()


def _department_by_code(department_code: str):
    return Department.objects.filter(code=department_code).first()


def report_un(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("UN")
    return _render_report_form(
        request,
        dept_code="UN",
        title="UN 報告フォーム（責任者まとめ報告）",
        location_label="現場名",
        members=_members_for_department("UN"),
        default_reporter_id=department.default_reporter_id if department else None,
    )


def report_wv(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("WV")
    return _render_report_form(
        request,
        dept_code="WV",
        title="WV 報告フォーム（責任者まとめ報告）",
        location_label="現場名",
        members=_members_for_department("WV"),
        default_reporter_id=department.default_reporter_id if department else None,
    )


def report_style1(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("STYLE1")
    return _render_report_form(
        request,
        dept_code="Style1",
        title="Style1 報告フォーム（責任者まとめ報告）",
        location_label="店舗",
        location_value="南町田",
        members=_members_for_department("STYLE1"),
        default_reporter_id=department.default_reporter_id if department else None,
    )


def report_style2(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("STYLE2")
    return _render_report_form(
        request,
        dept_code="Style2",
        title="Style2 報告フォーム（責任者まとめ報告）",
        location_label="店舗",
        location_value="港北",
        members=_members_for_department("STYLE2"),
        default_reporter_id=department.default_reporter_id if department else None,
    )
