from datetime import timedelta

from django.db.models import Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, require_roles
from apps.accounts.models import Department, Member
from apps.common.dashboard_snapshot import build_member_rows, build_submission_snapshot
from apps.common.report_metrics import (
    SPLIT_COUNT_CODES,
    collect_actual_totals,
    format_metric_triples,
    period_status as calc_period_status,
)
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric

from .forms import ReportSubmissionForm
from .models import DailyDepartmentReport, DailyDepartmentReportLine


REPORT_ROUTE_BY_DEPARTMENT_CODE = {
    "UN": "report_un",
    "WV": "report_wv",
    "STYLE1": "report_style1",
    "STYLE2": "report_style2",
}
ALLOWED_EDIT_REDIRECTS = {"dashboard_index", "report_history", *REPORT_ROUTE_BY_DEPARTMENT_CODE.values()}


def _dashboard_cards_context():
    today = timezone.localdate()
    target_departments = list(
        Department.objects.filter(is_active=True)
        .order_by("code")
        .values_list("code", "name")
    )
    snapshot = build_submission_snapshot(
        report_date=today,
        target_departments=target_departments,
    )
    target_codes = snapshot["target_codes"]
    submission_rows = snapshot["submission_rows"]
    daily_totals = snapshot["daily_totals"]
    member_totals = snapshot["member_totals"]

    current_month = today.replace(day=1)
    if not MonthTargetMetricValue.objects.filter(target_month=current_month).exists():
        latest_month = (
            MonthTargetMetricValue.objects.order_by("-target_month")
            .values_list("target_month", flat=True)
            .first()
        )
        if latest_month:
            current_month = latest_month

    month_target_rows = list(
        MonthTargetMetricValue.objects.filter(
            target_month=current_month,
            metric__is_active=True,
            department__code__in=target_codes,
        )
        .order_by("department__code", "metric__display_order", "id")
        .values("department__code", "metric_id", "value")
    )
    month_target_values_by_code = {code: {} for code in target_codes}
    for row in month_target_rows:
        month_target_values_by_code[row["department__code"]][row["metric_id"]] = row["value"]

    if current_month == today.replace(day=1):
        month_status = "active"
    elif current_month > today.replace(day=1):
        month_status = "planned"
    else:
        month_status = "finished"

    current_period = (
        Period.objects.filter(start_date__lte=today, end_date__gte=today)
        .order_by("-month", "start_date", "id")
        .first()
    )
    if not current_period:
        current_period = Period.objects.order_by("-month", "start_date", "id").first()

    if current_period:
        period_rows = list(
            PeriodTargetMetricValue.objects.filter(
                period=current_period,
                metric__is_active=True,
                department__code__in=target_codes,
            )
            .order_by("department__code", "metric__display_order", "id")
            .values("department__code", "metric_id", "value")
        )
        period_target_values_by_code = {code: {} for code in target_codes}
        for row in period_rows:
            period_target_values_by_code[row["department__code"]][row["metric_id"]] = row["value"]
        period_status = calc_period_status(
            today=today,
            start_date=current_period.start_date,
            end_date=current_period.end_date,
        )
        period_start = current_period.start_date
        period_end = current_period.end_date
        current_period_label = current_period.name
    else:
        period_target_values_by_code = {code: {} for code in target_codes}
        period_status = "-"
        period_start = today
        period_end = today
        current_period_label = "-"

    month_start = current_month
    if current_month.month == 12:
        month_end = current_month.replace(year=current_month.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = current_month.replace(month=current_month.month + 1, day=1) - timedelta(days=1)

    month_actual_totals_by_code = collect_actual_totals(
        start_date=month_start,
        end_date=month_end,
        target_codes=target_codes,
    )
    period_actual_totals_by_code = collect_actual_totals(
        start_date=period_start,
        end_date=period_end,
        target_codes=target_codes,
    )

    metrics_by_code = {}
    for code, _ in target_departments:
        department = Department.objects.filter(code=code).first()
        metrics_by_code[code] = list(
            TargetMetric.objects.filter(department=department, is_active=True).order_by("display_order", "id")
        ) if department else []

    target_progress_rows = []
    for code, label in target_departments:
        month_target_text, month_actual_text, month_rate_text = format_metric_triples(
            metrics=metrics_by_code[code],
            target_values=month_target_values_by_code.get(code, {}),
            actual_totals=month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        period_target_text, period_actual_text, period_rate_text = format_metric_triples(
            metrics=metrics_by_code[code],
            target_values=period_target_values_by_code.get(code, {}),
            actual_totals=period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        target_progress_rows.append(
            {
                "label": label,
                "month_target": month_target_text,
                "month_actual": month_actual_text,
                "month_rate": month_rate_text,
                "period_target": period_target_text,
                "period_actual": period_actual_text,
                "period_rate": period_rate_text,
            }
        )

    kpi_cards = []
    for code, label in target_departments:
        kpi_cards.append(
            {
                "code": code,
                "title": label,
                "count": daily_totals[code]["count"],
                "amount": daily_totals[code]["amount"],
                "has_split_counts": code in SPLIT_COUNT_CODES,
                "cs_count": daily_totals[code]["cs_count"],
                "refugee_count": daily_totals[code]["refugee_count"],
                "members": build_member_rows(member_totals=member_totals, codes=[code]),
            }
        )

    return {
        "today_str": today.strftime("%Y/%m/%d"),
        "submission_rows": submission_rows,
        "kpi_cards": kpi_cards,
        "target_month_summary": f"{current_month.year}/{current_month.month}",
        "target_month_status": month_status,
        "target_period_summary": current_period_label,
        "target_period_status": period_status,
        "target_progress_rows": target_progress_rows,
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
    context = {"department_buttons": department_buttons}
    context.update(_dashboard_cards_context())
    return render(request, "reports/report_index.html", context)


@require_roles(ROLE_ADMIN)
def report_history(request: HttpRequest) -> HttpResponse:
    reports = (
        DailyDepartmentReport.objects.select_related("department", "reporter")
        .prefetch_related("lines__member")
        .order_by("-report_date", "-created_at")[:100]
    )
    return render(request, "reports/report_history.html", {"reports": reports})


@require_roles(ROLE_REPORT, ROLE_ADMIN)
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
        split_counts=report.department.code in SPLIT_COUNT_CODES,
        editing_report=report,
        redirect_target=redirect_target,
    )


@require_roles(ROLE_REPORT, ROLE_ADMIN)
def report_delete(request: HttpRequest, dept_code: str, report_id: int) -> HttpResponse:
    if request.method != "POST":
        raise Http404

    normalized_code = dept_code.upper()
    report = get_object_or_404(
        DailyDepartmentReport.objects.select_related("department"),
        id=report_id,
    )
    if report.department.code != normalized_code:
        raise Http404

    report.delete()
    return redirect(reverse(REPORT_ROUTE_BY_DEPARTMENT_CODE.get(normalized_code, "report_index")))


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
    cs_counts = request.POST.getlist("cs_counts")
    refugee_counts = request.POST.getlist("refugee_counts")
    locations = request.POST.getlist("locations")
    size = max(len(member_ids), len(amounts), len(counts), len(cs_counts), len(refugee_counts), len(locations), 1)
    rows = []
    for i in range(size):
        rows.append(
            {
                "member_id": member_ids[i] if i < len(member_ids) else "",
                "amount": amounts[i] if i < len(amounts) else "0",
                "count": counts[i] if i < len(counts) else "0",
                "cs_count": cs_counts[i] if i < len(cs_counts) else "0",
                "refugee_count": refugee_counts[i] if i < len(refugee_counts) else "0",
                "location": locations[i] if i < len(locations) else "",
            }
        )
    return rows


def _parse_rows(*, rows, allowed_member_ids, split_counts=False):
    parsed_rows = []
    row_errors = []
    for idx, row in enumerate(rows, start=1):
        member_id_str = row["member_id"].strip()
        amount_str = row["amount"].strip() or "0"
        count_str = row["count"].strip() or "0"
        cs_count_str = row["cs_count"].strip() or "0"
        refugee_count_str = row["refugee_count"].strip() or "0"
        location = row["location"].strip()
        if not member_id_str:
            continue

        if not member_id_str.isdigit() or int(member_id_str) not in allowed_member_ids:
            row_errors.append(f"{idx}行目: メンバーが不正です。")
            continue

        try:
            amount = int(amount_str)
            if split_counts:
                cs_count = int(cs_count_str)
                refugee_count = int(refugee_count_str)
                count = cs_count + refugee_count
            else:
                count = int(count_str)
                cs_count = 0
                refugee_count = 0
        except ValueError:
            row_errors.append(f"{idx}行目: 金額と件数は数値で入力してください。")
            continue

        if amount < 0 or count < 0 or cs_count < 0 or refugee_count < 0:
            row_errors.append(f"{idx}行目: 金額と件数は0以上で入力してください。")
            continue

        parsed_rows.append(
            {
                "member_id": int(member_id_str),
                "amount": amount,
                "count": count,
                "cs_count": cs_count,
                "refugee_count": refugee_count,
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
                "cs_count": str(line.cs_count),
                "refugee_count": str(line.refugee_count),
                "location": line.location,
            }
        )
    if not rows:
        rows = [
            {"member_id": "", "amount": "0", "count": "0", "cs_count": "0", "refugee_count": "0", "location": ""},
        ]
    return rows


def _selected_report_date(request: HttpRequest):
    today = timezone.localdate()
    mode = request.GET.get("mode")
    if mode == "prev":
        return today - timedelta(days=1), "prev"
    return today, "today"


def _render_report_form(
    request: HttpRequest,
    *,
    dept_code: str,
    title: str,
    location_label: str,
    show_location: bool = True,
    split_counts: bool = False,
    editing_report: DailyDepartmentReport | None = None,
    redirect_target: str = "dashboard_index",
) -> HttpResponse:
    department = _department_by_code(dept_code)
    members = _members_for_department(dept_code)
    default_reporter_id = department.default_reporter_id if department else None
    selected_date, selected_mode = _selected_report_date(request)

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
        parsed_rows, row_errors = _parse_rows(
            rows=row_values,
            allowed_member_ids=allowed_member_ids,
            split_counts=split_counts,
        )

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
                        cs_count=row["cs_count"],
                        refugee_count=row["refugee_count"],
                        location=row["location"],
                    )
                    for row in parsed_rows
                ]
            )

            if editing_report:
                return redirect(redirect_target)
            return redirect(f"{reverse(request.resolver_match.view_name)}?submitted=1&mode={selected_mode}")
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
            initial = {"report_date": selected_date}
            if default_reporter_id:
                initial["reporter"] = default_reporter_id
            form = ReportSubmissionForm(initial=initial, members=members)
            row_values = [
                {"member_id": "", "amount": "0", "count": "0", "cs_count": "0", "refugee_count": "0", "location": ""},
            ]

    recent_reports = (
        DailyDepartmentReport.objects.filter(
            department__code=dept_code,
            report_date=selected_date,
        )
        .select_related("reporter")
        .annotate(
            cs_count_total=Sum("lines__cs_count"),
            refugee_count_total=Sum("lines__refugee_count"),
        )
        .order_by("-created_at")[:30]
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
            "split_counts": split_counts,
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
            "current_view_name": request.resolver_match.view_name if request.resolver_match else "",
            "selected_mode": selected_mode,
            "recent_reports_date": selected_date.strftime("%Y/%m/%d"),
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
        split_counts=True,
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


