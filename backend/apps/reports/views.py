from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member

from .forms import ReportSubmissionForm
from .models import DailyDepartmentReport, DailyDepartmentReportLine


def report_index(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/report_index.html")


def report_history(request: HttpRequest) -> HttpResponse:
    reports = (
        DailyDepartmentReport.objects.select_related("department", "reporter")
        .prefetch_related("lines__member")
        .order_by("-report_date", "-created_at")[:100]
    )
    return render(request, "reports/report_history.html", {"reports": reports})


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


def _build_row_values(*, request: HttpRequest, fixed_location: str):
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
                "location": fixed_location or (locations[i] if i < len(locations) else ""),
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


def _render_report_form(
    request: HttpRequest,
    *,
    dept_code: str,
    title: str,
    location_label: str,
    fixed_location: str = "",
) -> HttpResponse:
    department = _department_by_code(dept_code)
    members = _members_for_department(dept_code)
    default_reporter_id = department.default_reporter_id if department else None

    row_values = []
    row_errors = []

    if request.method == "POST":
        form = ReportSubmissionForm(request.POST, members=members)
        row_values = _build_row_values(request=request, fixed_location=fixed_location)
        allowed_member_ids = set(members.values_list("id", flat=True))
        parsed_rows, row_errors = _parse_rows(
            rows=row_values,
            allowed_member_ids=allowed_member_ids,
        )

        if form.is_valid() and not row_errors:
            department = _resolve_department(code=dept_code, label=dept_code)
            total_count = sum(row["count"] for row in parsed_rows)
            total_amount = sum(row["amount"] for row in parsed_rows)
            fallback_location = next(
                (row["location"] for row in parsed_rows if row["location"]),
                "",
            )
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
            return redirect(f"{reverse(request.resolver_match.view_name)}?submitted=1")
    else:
        initial = {"report_date": timezone.localdate()}
        if default_reporter_id:
            initial["reporter"] = default_reporter_id
        form = ReportSubmissionForm(initial=initial, members=members)
        row_values = [
            {"member_id": "", "amount": "0", "count": "0", "location": fixed_location},
            {"member_id": "", "amount": "0", "count": "0", "location": fixed_location},
        ]

    recent_reports = (
        DailyDepartmentReport.objects.filter(department__code=dept_code)
        .select_related("reporter")[:10]
    )

    return render(
        request,
        "reports/report_form.html",
        {
            "dept_code": dept_code,
            "title": title,
            "location_label": location_label,
            "fixed_location": fixed_location,
            "form": form,
            "members": members,
            "row_values": row_values,
            "row_errors": row_errors,
            "recent_reports": recent_reports,
            "submitted": request.GET.get("submitted") == "1",
        },
    )


def report_un(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="UN",
        title="UN 報告フォーム",
        location_label="現場",
    )


def report_wv(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="WV",
        title="WV 報告フォーム",
        location_label="現場",
    )


def report_style1(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="STYLE1",
        title="Style1 報告フォーム",
        location_label="現場",
        fixed_location="石巻方面",
    )


def report_style2(request: HttpRequest) -> HttpResponse:
    return _render_report_form(
        request,
        dept_code="STYLE2",
        title="Style2 報告フォーム",
        location_label="現場",
        fixed_location="郡山方面",
    )
