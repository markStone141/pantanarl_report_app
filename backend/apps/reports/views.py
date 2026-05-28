from django.db.models import Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.dateparse import parse_date
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, require_roles
from apps.accounts.models import Department, Member
from apps.common.report_metrics import SPLIT_COUNT_CODES
from apps.dairymetrics.models import MemberDailyMetricEntry
from apps.targets.models import Period

from .forms import ReportSubmissionForm
from .models import DailyDepartmentReport, DailyDepartmentReportLine
from .services.dashboard_cards import build_report_dashboard_cards_context, format_amount_text


REPORT_ROUTE_BY_DEPARTMENT_CODE = {
    "UN": "report_un",
    "WV": "report_wv",
    "STYLE1": "report_style1",
    "STYLE2": "report_style2",
}
ALLOWED_EDIT_REDIRECTS = {"dashboard_index", "report_history", *REPORT_ROUTE_BY_DEPARTMENT_CODE.values()}


def _history_query_string(*, date_from_str: str = "", date_to_str: str = "", date_on_str: str = "") -> str:
    query_params = {}
    if date_from_str:
        query_params["date_from"] = date_from_str
    if date_to_str:
        query_params["date_to"] = date_to_str
    if date_on_str:
        query_params["date_on"] = date_on_str
    if not query_params:
        return ""
    return f"?{urlencode(query_params)}"

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
    context.update(build_report_dashboard_cards_context())
    return render(request, "reports/report_index.html", context)


@require_roles(ROLE_ADMIN)
def report_history(request: HttpRequest) -> HttpResponse:
    date_from_str = (request.GET.get("date_from") or "").strip()
    date_to_str = (request.GET.get("date_to") or "").strip()
    date_on_str = (request.GET.get("date_on") or "").strip()
    date_from = parse_date(date_from_str) if date_from_str else None
    date_to = parse_date(date_to_str) if date_to_str else None
    date_on = parse_date(date_on_str) if date_on_str else None

    reports_query = DailyDepartmentReport.objects.select_related("department", "reporter").prefetch_related("lines__member")
    if date_on:
        reports_query = reports_query.filter(report_date=date_on)
    else:
        if date_from:
            reports_query = reports_query.filter(report_date__gte=date_from)
        if date_to:
            reports_query = reports_query.filter(report_date__lte=date_to)
    reports = list(reports_query.order_by("-report_date", "-created_at")[:100])

    filter_departments = list(
        Department.objects.filter(
            is_active=True,
            code__in=REPORT_ROUTE_BY_DEPARTMENT_CODE.keys(),
        )
        .order_by("code")
        .values("code", "name")
    )
    for report in reports:
        report.followup_count_text = _format_amount_text(report.followup_count)
        for line in report.lines.all():
            line.amount_text = _format_amount_text(line.amount)
    return render(
        request,
        "reports/report_history.html",
        {
            "reports": reports,
            "filter_departments": filter_departments,
            "date_from": date_from_str,
            "date_to": date_to_str,
            "date_on": date_on_str,
        },
    )


@require_roles(ROLE_ADMIN)
def report_bulk_delete(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        raise Http404

    selected_ids = []
    for raw_id in request.POST.getlist("selected_report_ids"):
        try:
            selected_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    if selected_ids:
        DailyDepartmentReport.objects.filter(id__in=selected_ids).delete()

    query_string = _history_query_string(
        date_from_str=(request.POST.get("date_from") or "").strip(),
        date_to_str=(request.POST.get("date_to") or "").strip(),
        date_on_str=(request.POST.get("date_on") or "").strip(),
    )
    return redirect(f"{reverse('report_history')}{query_string}")


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
        show_location=False,
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
    next_target = request.POST.get("next") or request.GET.get("next") or REPORT_ROUTE_BY_DEPARTMENT_CODE.get(normalized_code, "report_index")
    if next_target not in ALLOWED_EDIT_REDIRECTS:
        next_target = REPORT_ROUTE_BY_DEPARTMENT_CODE.get(normalized_code, "report_index")
    return redirect(reverse(next_target))


def _members_for_department(department_code: str):
    return (
        Member.objects.active().filter(
            department_links__department__code=department_code,
        )
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


def _build_initial_row_from_metric_entry(*, entry: MemberDailyMetricEntry, split_counts: bool, show_location: bool):
    return {
        "member_id": str(entry.member_id) if entry.member_id else "",
        "amount": str(entry.support_amount),
        "count": str(entry.result_count),
        "cs_count": str(entry.cs_count),
        "refugee_count": str(entry.refugee_count),
        "location": entry.location_name if show_location else "",
    }


def _build_dairymetrics_sync_context(
    *,
    department: Department | None,
    report_date,
    allowed_member_ids,
    split_counts: bool,
    show_location: bool,
):
    if not department or not report_date or not allowed_member_ids:
        return {"closed_entries": [], "active_entries": [], "initial_rows": []}

    entries = list(
        MemberDailyMetricEntry.objects.filter(
            department=department,
            entry_date=report_date,
            member_id__in=allowed_member_ids,
        )
        .select_related("member")
        .order_by("member__name", "id")
    )
    closed_entries = [entry for entry in entries if entry.activity_closed]
    active_entries = [entry for entry in entries if not entry.activity_closed]
    return {
        "closed_entries": closed_entries,
        "active_entries": active_entries,
        "initial_rows": [
            _build_initial_row_from_metric_entry(
                entry=entry,
                split_counts=split_counts,
                show_location=show_location,
            )
            for entry in closed_entries
        ],
    }


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
    allowed_member_ids = set(members.values_list("id", flat=True))

    if request.method == "POST":
        form = ReportSubmissionForm(request.POST, members=members)
        row_values = _build_row_values(request=request)
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
                report.edited_at = timezone.now()
                report.save(
                    update_fields=[
                        "report_date",
                        "reporter",
                        "total_count",
                        "followup_count",
                        "location",
                        "memo",
                        "edited_at",
                    ]
                )
                report.lines.all().delete()
            else:
                existing_reports = DailyDepartmentReport.objects.filter(
                    department=department,
                    report_date=form.cleaned_data["report_date"],
                ).order_by("-created_at", "-id")
                report = existing_reports.first()
                if report:
                    report.reporter = form.cleaned_data["reporter"]
                    report.total_count = total_count
                    report.followup_count = total_amount
                    report.location = fallback_location
                    report.memo = form.cleaned_data["memo"].strip()
                    report.edited_at = timezone.now()
                    report.save(
                        update_fields=[
                            "reporter",
                            "total_count",
                            "followup_count",
                            "location",
                            "memo",
                            "edited_at",
                        ]
                    )
                    report.lines.all().delete()
                    existing_reports.exclude(id=report.id).delete()
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
            dairymetrics_sync_context = _build_dairymetrics_sync_context(
                department=department,
                report_date=selected_date,
                allowed_member_ids=allowed_member_ids,
                split_counts=split_counts,
                show_location=show_location,
            )
            row_values = dairymetrics_sync_context["initial_rows"] or [
                {"member_id": "", "amount": "0", "count": "0", "cs_count": "0", "refugee_count": "0", "location": ""},
            ]

    report_date_for_context = selected_date
    if form.is_bound:
        report_date_for_context = parse_date((request.POST.get("report_date") or "").strip()) or selected_date
    elif editing_report:
        report_date_for_context = editing_report.report_date

    dairymetrics_sync_context = _build_dairymetrics_sync_context(
        department=department,
        report_date=report_date_for_context,
        allowed_member_ids=allowed_member_ids,
        split_counts=split_counts,
        show_location=show_location,
    )

    recent_reports = list(
        DailyDepartmentReport.objects.filter(
            department__code=dept_code,
            report_date=selected_date,
        )
        .select_related("reporter")
        .prefetch_related("lines__member")
        .annotate(
            cs_count_total=Sum("lines__cs_count"),
            refugee_count_total=Sum("lines__refugee_count"),
        )
        .order_by("-created_at")[:30]
    )
    for report in recent_reports:
        report.followup_count_text = _format_amount_text(report.followup_count)
        for line in report.lines.all():
            line.amount_text = _format_amount_text(line.amount)
    if form.is_bound:
        selected_reporter_id = str(form.data.get("reporter", "") or "")
        memo_value = form.data.get("memo", "") or ""
        report_date_value = str(form.data.get("report_date", "") or "")
    else:
        selected_reporter_id = str(form.initial.get("reporter", "") or "")
        memo_value = form.initial.get("memo", "") or ""
        initial_report_date = form.initial.get("report_date") or selected_date
        if hasattr(initial_report_date, "strftime"):
            report_date_value = initial_report_date.strftime("%Y-%m-%d")
        else:
            report_date_value = str(initial_report_date or "")

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
            "report_date_value": report_date_value,
            "submitted": request.GET.get("submitted") == "1",
            "is_edit": is_edit,
            "editing_report": editing_report,
            "redirect_target": redirect_target,
            "current_view_name": request.resolver_match.view_name if request.resolver_match else "",
            "selected_mode": selected_mode,
            "recent_reports_date": selected_date.strftime("%Y/%m/%d"),
            "today_iso": timezone.localdate().isoformat(),
            "dairymetrics_closed_entries": dairymetrics_sync_context["closed_entries"],
            "dairymetrics_active_entries": dairymetrics_sync_context["active_entries"],
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
        show_location=False,
    )


@require_roles(ROLE_REPORT, ROLE_ADMIN)
def report_wv(request: HttpRequest) -> HttpResponse:
    department = _department_by_code("WV")
    return _render_report_form(
        request,
        dept_code="WV",
        title=f"{department.name if department else 'WV'} 報告フォーム",
        location_label="現場",
        show_location=False,
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
