from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, require_roles
from apps.accounts.models import Department, Member

from .forms import ReportSubmissionForm
from .models import DailyDepartmentReport, DailyDepartmentReportLine


ALLOWED_EDIT_REDIRECTS = {"dashboard_index", "report_history"}
REPORT_ROUTE_BY_DEPARTMENT_CODE = {
    "UN": "report_un",
    "WV": "report_wv",
    "STYLE1": "report_style1",
    "STYLE2": "report_style2",
}


@require_roles(ROLE_REPORT, ROLE_ADMIN)
def report_index(request: HttpRequest) -> HttpResponse:
    department_map = {
        department.code: department.name
        for department in Department.objects.filter(
            is_active=True,
            code__in=REPORT_ROUTE_BY_DEPARTMENT_CODE.keys(),
        )
    }
    department_buttons = [
        {
            "name": department_map.get(code, code),
            "url_name": url_name,
        }
        for code, url_name in REPORT_ROUTE_BY_DEPARTMENT_CODE.items()
    ]
    return render(
        request,
        "reports/report_index.html",
        {"department_buttons": department_buttons},
    )


@require_roles(ROLE_ADMIN)
def report_history(request: HttpRequest) -> HttpResponse:
    reports = (
        DailyDepartmentReport.objects.select_related("department", "reporter")
        .prefetch_related("lines__member")
        .order_by("-report_date", "-created_at")[:100]
    )
    return render(request, "reports/report_history.html", {"reports": reports})


@require_roles(ROLE_ADMIN)
def report_edit(request: HttpRequest, report_id: int) -> HttpResponse:
    report = get_object_or_404(
        DailyDepartmentReport.objects.select_related("department", "reporter"),
        id=report_id,
    )
    redirect_target = request.GET.get("next") or request.POST.get("next") or "dashboard_index"
    if redirect_target not in ALLOWED_EDIT_REDIRECTS:
        redirect_target = "dashboard_index"

    return _render_report_form(
        request,
        dept_code=report.department.code,
        title=f"{report.department.name} 報告フォーム",
        location_label="現場",
        show_location=report.department.code not in {"STYLE1", "STYLE2"},
        editing_report=report,
        redirect_target=redirect_target,
    )


def _members_for_department(department_code: str):
    return (
        Member.objects.filter(department_links__department__code=department_code)
        .distinct()
        .order_by("name")
    )


def _department_by_code(department_code: str):
    return Department.objects.filter(code=department_code).first()


def _resolve_department(*, code: str, label: str) -> Department:
    department = _department_by_code(code)
    if department:
        return department
    return Department.objects.create(code=code, name=label)


def _build_row_values(*, request: HttpRequest):
    member_ids = request.POST.getlist("member_ids")
    amounts = request.POST.getlist("amounts")
    counts = request.POST.getlist("counts")
    locations = request.POST.getlist("locations")
    size = max(len(member_ids), len(amounts), len(counts), len(locations), 2)
    rows = []
    for i in range(size):
        rows.append(
            {
                "member_id": member_ids[i] if i < len(member_ids) else "",
                "amount": amounts[i] if i < len(amounts) else "0",
                "count": counts[i] if i < len(counts) else "0",
                "location": locations[i] if i < len(locations) else "",
            }
        )
    return rows


def _parse_rows(*, rows, allowed_member_ids):
    parsed_rows = []
    row_errors = []
    for idx, row in enumerate(rows, start=1):
        member_id_str = row["member_id"].strip()
        amount_str = row["amount"].strip() or "0"
        count_str = row["count"].strip() or "0"
        location = row["location"].strip()
        if not member_id_str:
            continue

        if not member_id_str.isdigit() or int(member_id_str) not in allowed_member_ids:
            row_errors.append(f"{idx}行目: メンバーが不正です。")
            continue

        try:
            amount = int(amount_str)
            count = int(count_str)
        except ValueError:
            row_errors.append(f"{idx}行目: 金額と件数は数値で入力してください。")
            continue

        if amount < 0 or count < 0:
            row_errors.append(f"{idx}行目: 金額と件数は0以上で入力してください。")
            continue

        parsed_rows.append(
            {
                "member_id": int(member_id_str),
                "amount": amount,
                "count": count,
                "location": location,
            }
        )

    if not parsed_rows:
        row_errors.append("メンバー行を1行以上入力してください。")

    return parsed_rows, row_errors


def _build_initial_rows_from_report(report: DailyDepartmentReport):
    rows = []
    for line in report.lines.select_related("member").all():
        rows.append(
            {
                "member_id": str(line.member_id) if line.member_id else "",
                "amount": str(line.amount),
                "count": str(line.count),
                "location": line.location,
            }
        )
    if not rows:
        rows = [
            {"member_id": "", "amount": "0", "count": "0", "location": ""},
            {"member_id": "", "amount": "0", "count": "0", "location": ""},
        ]
    return rows


def _render_report_form(
    request: HttpRequest,
    *,
    dept_code: str,
    title: str,
    location_label: str,
    show_location: bool = True,
    editing_report: DailyDepartmentReport | None = None,
    redirect_target: str = "dashboard_index",
) -> HttpResponse:
    department = _department_by_code(dept_code)
    members = _members_for_department(dept_code)
    default_reporter_id = department.default_reporter_id if department else None

    row_values = []
    row_errors = []
    is_edit = editing_report is not None

    if request.method == "POST":
        form = ReportSubmissionForm(request.POST, members=members)
        row_values = _build_row_values(request=request)
        allowed_member_ids = set(members.values_list("id", flat=True))
        if not show_location:
            for row in row_values:
                row["location"] = ""
        parsed_rows, row_errors = _parse_rows(rows=row_values, allowed_member_ids=allowed_member_ids)

        if form.is_valid() and not row_errors:
            department = _resolve_department(code=dept_code, label=dept_code)
            total_count = sum(row["count"] for row in parsed_rows)
            total_amount = sum(row["amount"] for row in parsed_rows)
            fallback_location = next((row["location"] for row in parsed_rows if row["location"]), "")

            if editing_report:
                report = editing_report
                report.report_date = form.cleaned_data["report_date"]
                report.reporter = form.cleaned_data["reporter"]
                report.total_count = total_count
                report.followup_count = total_amount
                report.location = fallback_location
                report.memo = form.cleaned_data["memo"].strip()
                report.save(
                    update_fields=[
                        "report_date",
                        "reporter",
                        "total_count",
                        "followup_count",
                        "location",
                        "memo",
                    ]
                )
                report.lines.all().delete()
            else:
                report = DailyDepartmentReport.objects.create(
                    department=department,
                    report_date=form.cleaned_data["report_date"],
                    reporter=form.cleaned_data["reporter"],
                    total_count=total_count,
                    followup_count=total_amount,
                    location=fallback_location,
                    memo=form.cleaned_data["memo"].strip(),
                )

            member_map = {member.id: member for member in members}
            DailyDepartmentReportLine.objects.bulk_create(
                [
                    DailyDepartmentReportLine(
                        report=report,
                        member=member_map[row["member_id"]],
                        amount=row["amount"],
                        count=row["count"],
                        location=row["location"],
                    )
                    for row in parsed_rows
                ]
            )

            if editing_report:
                return redirect(redirect_target)
            return redirect(f"{reverse(request.resolver_match.view_name)}?submitted=1")
    else:
        if editing_report:
            form = ReportSubmissionForm(
                initial={
                    "report_date": editing_report.report_date,
                    "reporter": editing_report.reporter_id,
                    "memo": editing_report.memo,
                },
                members=members,
            )
            row_values = _build_initial_rows_from_report(editing_report)
            if not show_location:
                for row in row_values:
                    row["location"] = ""
        else:
            initial = {"report_date": timezone.localdate()}
            if default_reporter_id:
                initial["reporter"] = default_reporter_id
            form = ReportSubmissionForm(initial=initial, members=members)
            row_values = [
                {"member_id": "", "amount": "0", "count": "0", "location": ""},
                {"member_id": "", "amount": "0", "count": "0", "location": ""},
            ]

    recent_reports = (
        DailyDepartmentReport.objects.filter(department__code=dept_code).select_related("reporter")[:10]
    )
    if form.is_bound:
        selected_reporter_id = str(form.data.get("reporter", "") or "")
        memo_value = form.data.get("memo", "") or ""
    else:
        selected_reporter_id = str(form.initial.get("reporter", "") or "")
        memo_value = form.initial.get("memo", "") or ""

    return render(
        request,
        "reports/report_form.html",
        {
            "dept_code": dept_code,
            "dept_name": department.name if department else dept_code,
            "title": title,
            "location_label": location_label,
            "show_location": show_location,
            "form": form,
            "members": members,
            "row_values": row_values,
            "row_errors": row_errors,
            "recent_reports": recent_reports,
            "selected_reporter_id": selected_reporter_id,
            "memo_value": memo_value,
            "submitted": request.GET.get("submitted") == "1",
            "is_edit": is_edit,
            "editing_report": editing_report,
            "redirect_target": redirect_target,
        },
    )


@require_roles(ROLE_REPORT, ROLE_ADMIN)
def report_un(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("UN")
    return _render_report_form(
        request,
        dept_code="UN",
        title=f"{department.name if department else 'UN'} 報告フォーム",
        location_label="現場",
    )


@require_roles(ROLE_REPORT, ROLE_ADMIN)
def report_wv(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("WV")
    return _render_report_form(
        request,
        dept_code="WV",
        title=f"{department.name if department else 'WV'} 報告フォーム",
        location_label="現場",
    )


@require_roles(ROLE_REPORT, ROLE_ADMIN)
def report_style1(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("STYLE1")
    return _render_report_form(
        request,
        dept_code="STYLE1",
        title=f"{department.name if department else 'Style1'} 報告フォーム",
        location_label="現場",
        show_location=False,
    )


@require_roles(ROLE_REPORT, ROLE_ADMIN)
def report_style2(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("STYLE2")
    return _render_report_form(
        request,
        dept_code="STYLE2",
        title=f"{department.name if department else 'Style2'} 報告フォーム",
        location_label="現場",
        show_location=False,
    )
