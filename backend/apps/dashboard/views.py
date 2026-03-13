import logging
import re
from datetime import timedelta

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, require_roles
from apps.accounts.models import Department, Member, MemberDepartment
from apps.common.dashboard_snapshot import build_member_rows, build_submission_snapshot
from apps.common.report_metrics import (
    SPLIT_COUNT_CODES,
    collect_actual_totals,
    format_metric_triples,
    format_yen,
    metric_detail_rows,
    period_status as calc_period_status,
)
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric

from .forms import DepartmentForm, MemberRegistrationForm, TargetMetricForm

User = get_user_model()
logger = logging.getLogger(__name__)


def _format_amount_text(value):
    if isinstance(value, int):
        return f"{value:,}"
    return value


def _mail_period_heading(period_name: str) -> str:
    match = re.search(r"第\d+次路程", period_name or "")
    return match.group(0) if match else (period_name or "-")


def _dashboard_index_impl(request: HttpRequest) -> HttpResponse:
    real_today = timezone.localdate()
    selected_mode = "prev" if request.GET.get("mode") == "prev" else "today"
    today = real_today - timedelta(days=1) if selected_mode == "prev" else real_today
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
    for row in submission_rows:
        row["amount_text"] = _format_amount_text(row.get("amount"))


    current_month = today.replace(day=1)

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
        current_period_label = current_period.name
        period_status = calc_period_status(
            today=today,
            start_date=current_period.start_date,
            end_date=current_period.end_date,
        )
        period_start = current_period.start_date
        period_end = current_period.end_date
        current_period_range = (
            f"{current_period.start_date.month}/{current_period.start_date.day}"
            f"～{current_period.end_date.month}/{current_period.end_date.day}"
        )
    else:
        current_period_label = "-"
        period_status = "-"
        period_target_values_by_code = {code: {} for code in target_codes}
        period_start = None
        period_end = None
        current_period_range = "-"

    month_start = current_month
    if current_month.month == 12:
        month_end = current_month.replace(year=current_month.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = current_month.replace(month=current_month.month + 1, day=1) - timedelta(days=1)

    month_actual_totals_by_code = collect_actual_totals(
        start_date=month_start,
        end_date=month_end,
        target_codes=target_codes,
        include_adjustments=True,
    )
    if period_start and period_end:
        period_actual_totals_by_code = collect_actual_totals(
            start_date=period_start,
            end_date=period_end,
            target_codes=target_codes,
            include_adjustments=True,
        )
    else:
        period_actual_totals_by_code = {
            code: {"count": 0, "amount": 0, "cs_count": 0, "refugee_count": 0}
            for code in target_codes
        }

    metrics_by_code = {}
    for code, label in target_departments:
        department = Department.objects.filter(code=code).first()
        if department:
            metrics_by_code[code] = list(
                TargetMetric.objects.filter(department=department, is_active=True).order_by("display_order", "id")
            )
        else:
            metrics_by_code[code] = []

    target_progress_rows = []
    metric_detail_by_code = {}
    for code, label in target_departments:
        month_metric_rows = metric_detail_rows(
            metrics=metrics_by_code[code],
            target_values=month_target_values_by_code.get(code, {}),
            actual_totals=month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        period_metric_rows = metric_detail_rows(
            metrics=metrics_by_code[code],
            target_values=period_target_values_by_code.get(code, {}),
            actual_totals=period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        metric_detail_by_code[code] = {
            "month": month_metric_rows,
            "period": period_metric_rows,
        }
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
        member_rows = build_member_rows(member_totals=member_totals, codes=[code])
        for member_row in member_rows:
            member_row["amount_text"] = _format_amount_text(member_row.get("amount", 0))
        kpi_cards.append(
            {
                "code": code,
                "title": label,
                "count": daily_totals[code]["count"],
                "amount": daily_totals[code]["amount"],
                "amount_text": _format_amount_text(daily_totals[code]["amount"]),
                "has_split_counts": code in SPLIT_COUNT_CODES,
                "cs_count": daily_totals[code]["cs_count"],
                "refugee_count": daily_totals[code]["refugee_count"],
                "members": member_rows,
            }
        )

    label_by_code = {code: label for code, label in target_departments}

    def build_mail_template_payload(base_date):
        base_snapshot = build_submission_snapshot(
            report_date=base_date,
            target_departments=target_departments,
        )
        base_daily_totals = base_snapshot["daily_totals"]
        base_member_totals = base_snapshot["member_totals"]
        base_has_report_by_code = base_snapshot["has_report_by_code"]

        base_month = base_date.replace(day=1)

        base_month_target_rows = list(
            MonthTargetMetricValue.objects.filter(
                target_month=base_month,
                metric__is_active=True,
                department__code__in=target_codes,
            )
            .order_by("department__code", "metric__display_order", "id")
            .values("department__code", "metric_id", "value")
        )
        base_month_target_values_by_code = {code: {} for code in target_codes}
        for row in base_month_target_rows:
            base_month_target_values_by_code[row["department__code"]][row["metric_id"]] = row["value"]

        base_period = (
            Period.objects.filter(start_date__lte=base_date, end_date__gte=base_date)
            .order_by("-month", "start_date", "id")
            .first()
        )

        if base_period:
            base_period_rows = list(
                PeriodTargetMetricValue.objects.filter(
                    period=base_period,
                    metric__is_active=True,
                    department__code__in=target_codes,
                )
                .order_by("department__code", "metric__display_order", "id")
                .values("department__code", "metric_id", "value")
            )
            base_period_target_values_by_code = {code: {} for code in target_codes}
            for row in base_period_rows:
                base_period_target_values_by_code[row["department__code"]][row["metric_id"]] = row["value"]
            base_period_start = base_period.start_date
            base_period_end = base_period.end_date
            base_period_name = _mail_period_heading(base_period.name)
            base_period_range = (
                f"{base_period.start_date.month}/{base_period.start_date.day}"
                f"～{base_period.end_date.month}/{base_period.end_date.day}"
            )
        else:
            base_period_target_values_by_code = {code: {} for code in target_codes}
            base_period_start = None
            base_period_end = None
            base_period_name = "-"
            base_period_range = "-"

        if base_month.month == 12:
            base_month_end = base_month.replace(year=base_month.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            base_month_end = base_month.replace(month=base_month.month + 1, day=1) - timedelta(days=1)

        base_month_actual_totals_by_code = collect_actual_totals(
            start_date=base_month,
            end_date=base_month_end,
            target_codes=target_codes,
            include_adjustments=True,
        )
        if base_period_start and base_period_end:
            base_period_actual_totals_by_code = collect_actual_totals(
                start_date=base_period_start,
                end_date=base_period_end,
                target_codes=target_codes,
                include_adjustments=True,
            )
        else:
            base_period_actual_totals_by_code = {
                code: {"count": 0, "amount": 0, "cs_count": 0, "refugee_count": 0}
                for code in target_codes
            }

        base_metric_detail_by_code = {}
        for code, _ in target_departments:
            base_metric_detail_by_code[code] = {
                "month": metric_detail_rows(
                    metrics=metrics_by_code.get(code, []),
                    target_values=base_month_target_values_by_code.get(code, {}),
                    actual_totals=base_month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
                ),
                "period": metric_detail_rows(
                    metrics=metrics_by_code.get(code, []),
                    target_values=base_period_target_values_by_code.get(code, {}),
                    actual_totals=base_period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
                ),
            }

        def build_remaining_values(detail_rows):
            remaining_count = 0
            remaining_cs_count = 0
            remaining_refugee_count = 0
            remaining_amount = 0

            def _is_amount(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return (
                    code_text == "amount"
                    or "amount" in code_text
                    or "yen" in code_text
                    or "money" in code_text
                    or "support" in code_text
                    or "followup" in code_text
                    or "kingaku" in code_text
                    or "円" in unit_text
                )

            def _is_cs_count(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return "cs" in code_text or "cs" in unit_text

            def _is_refugee_count(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return "refugee" in code_text or "nanmin" in code_text or "難民" in unit_text

            def _is_count(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return (
                    code_text == "count"
                    or "count" in code_text
                    or "kensu" in code_text
                    or "case" in code_text
                    or "num" in code_text
                    or "cs" in code_text
                    or "refugee" in code_text
                    or "nanmin" in code_text
                    or "件" in unit_text
                )

            for row in detail_rows:
                target = row.get("target") or 0
                actual = row.get("actual") or 0
                delta = target - actual
                code = row.get("code") or ""
                unit = row.get("unit") or ""
                if _is_amount(code, unit):
                    remaining_amount += delta
                elif _is_cs_count(code, unit):
                    remaining_cs_count += delta
                    remaining_count += delta
                elif _is_refugee_count(code, unit):
                    remaining_refugee_count += delta
                    remaining_count += delta
                elif _is_count(code, unit):
                    remaining_count += delta

            def _signed_count_text(value: int) -> str:
                if value < 0:
                    return f"+{abs(value)}件"
                return f"{value}件"

            def _signed_yen_text(value: int) -> str:
                if value < 0:
                    return f"+{abs(value):,}円"
                return f"{value:,}円"

            return {
                "count": remaining_count,
                "cs_count": remaining_cs_count,
                "refugee_count": remaining_refugee_count,
                "amount": remaining_amount,
                "text": f"{_signed_count_text(remaining_count)}/{_signed_yen_text(remaining_amount)}",
                "split_text": (
                    f"CS{_signed_count_text(remaining_cs_count)} "
                    f"難民{_signed_count_text(remaining_refugee_count)}/"
                    f"{_signed_yen_text(remaining_amount)}"
                ),
            }

        section_order = [
            ("UN", "UN①"),
            ("WV", "UN②"),
            ("STYLE2", "Styleチーム"),
            ("STYLE1", "Styleチーム"),
        ]
        mail_sections = []
        for code, heading in section_order:
            if code not in label_by_code:
                continue
            member_lines = [
                {
                    "name": row["member_name"],
                    "count": row["count"],
                    "cs_count": row.get("cs_count", 0),
                    "refugee_count": row.get("refugee_count", 0),
                    "amount_text": format_yen(row["amount"]),
                }
                for row in build_member_rows(member_totals=base_member_totals, codes=[code])
            ]
            month_metric_lines = [
                f"{row['label']} {row['actual_text']}/{row['target_text']}{row['unit']} 達成率{row['rate']}"
                for row in base_metric_detail_by_code.get(code, {}).get("month", [])
            ]
            period_metric_lines = [
                f"{row['label']} {row['actual_text']}/{row['target_text']}{row['unit']} 達成率{row['rate']}"
                for row in base_metric_detail_by_code.get(code, {}).get("period", [])
            ]
            month_remaining = build_remaining_values(base_metric_detail_by_code.get(code, {}).get("month", []))
            period_remaining = build_remaining_values(base_metric_detail_by_code.get(code, {}).get("period", []))
            mail_sections.append(
                {
                    "code": code,
                    "heading": heading,
                    "name": label_by_code[code],
                    "has_report": base_has_report_by_code.get(code, False),
                    "daily_count": base_daily_totals.get(code, {}).get("count", 0),
                    "daily_cs_count": base_daily_totals.get(code, {}).get("cs_count", 0),
                    "daily_refugee_count": base_daily_totals.get(code, {}).get("refugee_count", 0),
                    "daily_amount_text": format_yen(base_daily_totals.get(code, {}).get("amount", 0)),
                    "member_lines": member_lines,
                    "period_lines": period_metric_lines,
                    "month_lines": month_metric_lines,
                    "period_remaining_text": period_remaining["text"],
                    "month_remaining_text": month_remaining["text"],
                    "period_remaining_split_text": period_remaining["split_text"],
                    "month_remaining_split_text": month_remaining["split_text"],
                }
            )

        un_wv_codes = [code for code in ["UN", "WV"] if code in label_by_code]
        un_wv_month_actual = sum(
            base_month_actual_totals_by_code.get(code, {"amount": 0})["amount"] for code in un_wv_codes
        )
        un_wv_month_target = 0
        for code in un_wv_codes:
            for metric in metrics_by_code.get(code, []):
                if metric.code == "amount":
                    un_wv_month_target += base_month_target_values_by_code.get(code, {}).get(metric.id, 0)
        un_wv_month_rate = (
            f"{(un_wv_month_actual / un_wv_month_target) * 100:.1f}%"
            if un_wv_month_target > 0
            else "-"
        )

        return {
            "report_date": base_date.strftime("%Y/%m/%d"),
            "sections": mail_sections,
            "period_name": base_period_name,
            "period_range": base_period_range,
            "un_wv_summary": {
                "actual_text": format_yen(un_wv_month_actual),
                "target_text": format_yen(un_wv_month_target),
                "rate": un_wv_month_rate,
            },
        }

    mail_template_payload_map = {
        "today": build_mail_template_payload(real_today),
        "prev": build_mail_template_payload(real_today - timedelta(days=1)),
    }

    context = {
        "today_str": today.strftime("%Y/%m/%d"),
        "submission_rows": submission_rows,
        "kpi_cards": kpi_cards,
        "target_month_summary": f"{current_month.year}/{current_month.month}",
        "target_month_status": month_status,
        "target_period_summary": current_period_label,
        "target_period_status": period_status,
        "target_period_range": current_period_range,
        "current_period_label": current_period_label,
        "target_progress_rows": target_progress_rows,
        "mail_template_payload_map": mail_template_payload_map,
        "selected_mode": selected_mode,
    }
    return render(request, "dashboard/admin.html", context)


@require_roles(ROLE_ADMIN)
def dashboard_index(request: HttpRequest) -> HttpResponse:
    try:
        return _dashboard_index_impl(request)
    except Exception:
        logger.exception("dashboard_index failed")
        today = timezone.localdate()
        return render(
            request,
            "dashboard/admin.html",
            {
                "today_str": today.strftime("%Y/%m/%d"),
                "submission_rows": [],
                "kpi_cards": [],
                "target_month_summary": f"{today.year}/{today.month}",
                "target_month_status": "-",
                "target_period_summary": "-",
                "target_period_status": "-",
                "target_period_range": "-",
                "current_period_label": "-",
                "target_progress_rows": [],
                "mail_template_payload_map": {
                    "today": {
                        "report_date": today.strftime("%Y/%m/%d"),
                        "sections": [],
                        "period_name": "-",
                        "period_range": "-",
                        "un_wv_summary": {"actual_text": "0円", "target_text": "0円", "rate": "-"},
                    },
                    "prev": {
                        "report_date": (today - timedelta(days=1)).strftime("%Y/%m/%d"),
                        "sections": [],
                        "period_name": "-",
                        "period_range": "-",
                        "un_wv_summary": {"actual_text": "0円", "target_text": "0円", "rate": "-"},
                    },
                },
                "selected_mode": "today",
            },
        )


def _member_form(*, data=None, initial=None) -> MemberRegistrationForm:
    form = MemberRegistrationForm(data=data, initial=initial)
    active_departments = Department.objects.filter(is_active=True)
    form.fields["departments"].queryset = active_departments
    form.fields["default_department"].queryset = active_departments
    return form


def _department_form(*, data=None, initial=None, edit_department=None) -> DepartmentForm:
    form = DepartmentForm(data=data, initial=initial)
    if edit_department:
        reporter_ids = Member.objects.active().filter(
            department_links__department=edit_department,
        ).values_list("id", flat=True)
        form.fields["default_reporter"].queryset = Member.objects.active().filter(
            id__in=reporter_ids,
        ).order_by("name")
    else:
        form.fields["default_reporter"].queryset = Member.objects.none()
    return form


def _target_metric_form(*, data=None, initial=None) -> TargetMetricForm:
    return TargetMetricForm(data=data, initial=initial)


@require_roles(ROLE_ADMIN)
def member_delete(request: HttpRequest, member_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("member_settings")

    member = get_object_or_404(Member, id=member_id)
    linked_user = member.user
    member.is_active = not member.is_active
    member.save(update_fields=["is_active"])
    if linked_user and not linked_user.is_superuser:
        linked_user.is_active = member.is_active
        linked_user.save(update_fields=["is_active"])
    return redirect("member_settings")


@require_roles(ROLE_ADMIN)
def member_purge(request: HttpRequest, member_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("member_settings")

    member = get_object_or_404(Member, id=member_id)
    if member.is_active:
        return redirect("member_settings")

    linked_user = member.user
    member.delete()
    if linked_user and not linked_user.is_superuser:
        linked_user.delete()
    return redirect("member_settings")


@require_roles(ROLE_ADMIN)
def department_settings(request: HttpRequest) -> HttpResponse:
    status_message = None
    edit_department = None
    selected_metric_department = None
    edit_metric = None

    edit_id = request.GET.get("edit")
    if edit_id and edit_id.isdigit():
        edit_department = Department.objects.filter(id=int(edit_id)).first()

    metric_department_id = request.GET.get("metric_department")
    if metric_department_id and metric_department_id.isdigit():
        selected_metric_department = Department.objects.filter(id=int(metric_department_id)).first()
    if not selected_metric_department:
        selected_metric_department = edit_department or Department.objects.order_by("code").first()

    form = _department_form(
        initial={
            "name": edit_department.name,
            "code": edit_department.code,
            "default_reporter": edit_department.default_reporter_id,
        }
        if edit_department
        else None,
        edit_department=edit_department,
    )
    metric_form = _target_metric_form(initial={"display_order": 1, "is_active": True})

    edit_metric_id = request.GET.get("edit_metric")
    if edit_metric_id and edit_metric_id.isdigit() and selected_metric_department:
        edit_metric = TargetMetric.objects.filter(
            id=int(edit_metric_id),
            department=selected_metric_department,
        ).first()
        if edit_metric:
            metric_form = _target_metric_form(
                initial={
                    "label": edit_metric.label,
                    "code": edit_metric.code,
                    "unit": edit_metric.unit,
                    "display_order": edit_metric.display_order,
                    "is_active": edit_metric.is_active,
                }
            )

    if request.method == "POST":
        action = request.POST.get("action") or "save_department"
        if action == "save_department":
            edit_department_id = request.POST.get("edit_department_id")
            if edit_department_id and edit_department_id.isdigit():
                edit_department = Department.objects.filter(id=int(edit_department_id)).first()
            form = _department_form(data=request.POST, edit_department=edit_department)
            if form.is_valid():
                code = form.cleaned_data["code"].strip().upper()
                default_reporter = form.cleaned_data["default_reporter"]
                duplicate_query = Department.objects.filter(code=code)
                if edit_department_id and edit_department_id.isdigit():
                    duplicate_query = duplicate_query.exclude(id=int(edit_department_id))

                if duplicate_query.exists():
                    form.add_error("code", "この部署コードはすでに使用されています。")
                else:
                    if edit_department_id and edit_department_id.isdigit():
                        department = get_object_or_404(Department, id=int(edit_department_id))
                        if default_reporter and not MemberDepartment.objects.filter(
                            member=default_reporter,
                            department=department,
                        ).exists():
                            form.add_error(
                                "default_reporter",
                                "責任者は選択中の部署に所属するメンバーを選んでください。",
                            )
                        else:
                            department.name = form.cleaned_data["name"].strip()
                            department.code = code
                            department.default_reporter = default_reporter
                            department.save(update_fields=["name", "code", "default_reporter"])
                            status_message = f"{department.name}（{department.code}）を更新しました。"
                            edit_department = None
                            form = _department_form()
                    else:
                        department = Department.objects.create(
                            name=form.cleaned_data["name"].strip(),
                            code=code,
                            default_reporter=None,
                            is_active=True,
                        )
                        status_message = f"{department.name}（{department.code}）を追加しました。"
                        edit_department = None
                        form = _department_form()

        if action == "save_metric":
            metric_department_id = request.POST.get("metric_department_id")
            selected_metric_department = (
                Department.objects.filter(id=int(metric_department_id)).first()
                if metric_department_id and metric_department_id.isdigit()
                else None
            )
            edit_metric_id = request.POST.get("edit_metric_id")
            edit_metric = (
                TargetMetric.objects.filter(id=int(edit_metric_id)).first()
                if edit_metric_id and edit_metric_id.isdigit()
                else None
            )
            metric_form = _target_metric_form(data=request.POST)
            if not selected_metric_department:
                metric_form.add_error(None, "部署を選択してください。")
            elif metric_form.is_valid():
                metric_code = metric_form.cleaned_data["code"].strip().lower()
                duplicate_query = TargetMetric.objects.filter(
                    department=selected_metric_department,
                    code=metric_code,
                )
                if edit_metric:
                    duplicate_query = duplicate_query.exclude(id=edit_metric.id)

                if duplicate_query.exists():
                    metric_form.add_error("code", "この指標コードはすでに使用されています。")
                else:
                    if edit_metric:
                        edit_metric.department = selected_metric_department
                        edit_metric.label = metric_form.cleaned_data["label"].strip()
                        edit_metric.code = metric_code
                        edit_metric.unit = metric_form.cleaned_data["unit"].strip()
                        edit_metric.display_order = metric_form.cleaned_data["display_order"]
                        edit_metric.is_active = metric_form.cleaned_data["is_active"]
                        edit_metric.save(
                            update_fields=[
                                "department",
                                "label",
                                "code",
                                "unit",
                                "display_order",
                                "is_active",
                                "updated_at",
                            ]
                        )
                        status_message = "目標指標を更新しました。"
                    else:
                        TargetMetric.objects.create(
                            department=selected_metric_department,
                            label=metric_form.cleaned_data["label"].strip(),
                            code=metric_code,
                            unit=metric_form.cleaned_data["unit"].strip(),
                            display_order=metric_form.cleaned_data["display_order"],
                            is_active=metric_form.cleaned_data["is_active"],
                        )
                        status_message = "目標指標を追加しました。"
                    metric_form = _target_metric_form(initial={"display_order": 1, "is_active": True})
                    edit_metric = None

        if action == "toggle_metric":
            metric_id = request.POST.get("metric_id")
            if metric_id and metric_id.isdigit():
                metric = get_object_or_404(TargetMetric, id=int(metric_id))
                metric.is_active = not metric.is_active
                metric.save(update_fields=["is_active", "updated_at"])
                selected_metric_department = metric.department
                status_message = "目標指標の有効状態を更新しました。"

    departments = Department.objects.all()
    metrics = TargetMetric.objects.none()
    if selected_metric_department:
        metrics = TargetMetric.objects.filter(department=selected_metric_department).order_by("display_order", "id")

    return render(
        request,
        "dashboard/department_settings.html",
        {
            "form": form,
            "departments": departments,
            "edit_department": edit_department,
            "status_message": status_message,
            "metric_form": metric_form,
            "metrics": metrics,
            "selected_metric_department": selected_metric_department,
            "edit_metric": edit_metric,
        },
    )


@require_roles(ROLE_ADMIN)
def department_delete(request: HttpRequest, department_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("department_settings")

    department = get_object_or_404(Department, id=department_id)
    department.delete()
    return redirect("department_settings")


@require_roles(ROLE_ADMIN)
def member_settings(request: HttpRequest) -> HttpResponse:
    status_message = None
    edit_member = None

    edit_id = request.GET.get("edit")
    if edit_id and edit_id.isdigit():
        edit_member = Member.objects.filter(id=int(edit_id)).first()

    if request.method == "POST":
        edit_member_id = request.POST.get("edit_member_id")
        form = _member_form(data=request.POST)
        if form.is_valid():
            departments = form.cleaned_data["departments"]
            default_department = form.cleaned_data["default_department"]
            member_name = form.cleaned_data["name"].strip()
            auth_login_id = (form.cleaned_data.get("auth_login_id") or "").strip()
            auth_password = (form.cleaned_data.get("auth_password") or "").strip()
            linked_user = None

            if default_department and default_department not in departments:
                form.add_error("default_department", "メイン部署は所属部署から選択してください。")

            if not form.errors and edit_member_id and edit_member_id.isdigit():
                member = get_object_or_404(Member, id=int(edit_member_id))
                member.name = member_name
                member.default_department = default_department
                linked_user = member.user
                if auth_password and not auth_login_id and not linked_user:
                    form.add_error("auth_login_id", "パスワードを設定する場合はログインIDを入力してください。")
                if auth_login_id:
                    duplicate_user = User.objects.filter(username=auth_login_id)
                    if linked_user:
                        duplicate_user = duplicate_user.exclude(id=linked_user.id)
                    if duplicate_user.exists():
                        form.add_error("auth_login_id", "このログインIDはすでに使用されています。")
                    else:
                        if not linked_user:
                            if not auth_password:
                                form.add_error("auth_password", "新規連携時はパスワードを入力してください。")
                                linked_user = None
                            else:
                                linked_user = User.objects.create_user(
                                    username=auth_login_id,
                                    password=auth_password,
                                )
                        else:
                            linked_user.username = auth_login_id
                            linked_user.save(update_fields=["username"])
                if not form.errors:
                    if linked_user and auth_password:
                        linked_user.set_password(auth_password)
                        linked_user.save(update_fields=["password"])
                    member.user = linked_user
                    member.save(update_fields=["name", "user", "default_department"])
                    status_message = f"{member.name} を更新しました。"
            elif not form.errors:
                if auth_login_id and not auth_password:
                    form.add_error("auth_password", "新規作成時、ログインIDを設定する場合はパスワードが必要です。")
                elif auth_password and not auth_login_id:
                    form.add_error("auth_login_id", "パスワードを設定する場合はログインIDを入力してください。")
                else:
                    if auth_login_id:
                        if User.objects.filter(username=auth_login_id).exists():
                            form.add_error("auth_login_id", "このログインIDはすでに使用されています。")
                    if not form.errors:
                        if auth_login_id:
                            linked_user = User.objects.create_user(
                                username=auth_login_id,
                                password=auth_password,
                            )
                        member = Member.objects.create(
                            name=member_name,
                            user=linked_user,
                            default_department=default_department,
                        )
                        status_message = f"{member.name} を登録しました。"

            if not form.errors:
                MemberDepartment.objects.filter(member=member).exclude(department__in=departments).delete()
                existing_departments = set(
                    MemberDepartment.objects.filter(member=member).values_list("department_id", flat=True)
                )
                for dept in departments:
                    if dept.id not in existing_departments:
                        MemberDepartment.objects.create(member=member, department=dept)

                form = _member_form()
                edit_member = None
    else:
        if edit_member:
            form = _member_form(
                initial={
                    "name": edit_member.name,
                    "departments": list(edit_member.department_links.values_list("department_id", flat=True)),
                    "default_department": edit_member.default_department_id,
                    "auth_login_id": edit_member.user.username if edit_member.user else "",
                }
            )
        else:
            form = _member_form()

    members = (
        Member.objects.prefetch_related("department_links")
        .select_related("default_department")
        .select_related("user")
        .order_by("-is_active", "name")
    )
    selected_department_ids = {
        str(dept_id) for dept_id in (form["departments"].value() or [])
    }
    department_choices = Department.objects.filter(is_active=True).order_by("code")
    return render(
        request,
        "dashboard/member_settings.html",
        {
            "form": form,
            "members": members,
            "edit_member": edit_member,
            "status_message": status_message,
            "department_choices": department_choices,
            "selected_department_ids": selected_department_ids,
        },
    )


@require_roles(ROLE_ADMIN)
def member_auth_bulk_settings(request: HttpRequest) -> HttpResponse:
    members_qs = Member.objects.select_related("user").order_by("name", "id")
    paginator = Paginator(members_qs, 20)
    current_page_number = request.GET.get("page") or "1"
    page_obj = paginator.get_page(current_page_number)
    status_message = None
    row_errors = {}
    row_login_inputs = {}

    if request.method == "POST":
        posted_page = request.POST.get("page") or "1"
        page_obj = paginator.get_page(posted_page)
        updated_count = 0

        for member in page_obj.object_list:
            login_key = f"login_id_{member.id}"
            password_key = f"password_{member.id}"
            auth_login_id = (request.POST.get(login_key) or "").strip()
            auth_password = (request.POST.get(password_key) or "").strip()
            row_login_inputs[member.id] = auth_login_id
            errors = []

            if not auth_login_id and not auth_password:
                continue

            linked_user = member.user
            changed = False

            if linked_user:
                if auth_login_id:
                    duplicate_user = User.objects.filter(username=auth_login_id).exclude(id=linked_user.id)
                    if duplicate_user.exists():
                        errors.append("このログインIDはすでに使用されています。")
                    elif linked_user.username != auth_login_id:
                        linked_user.username = auth_login_id
                        linked_user.save(update_fields=["username"])
                        changed = True
                if auth_password:
                    linked_user.set_password(auth_password)
                    linked_user.save(update_fields=["password"])
                    changed = True
            else:
                if auth_password and not auth_login_id:
                    errors.append("新規連携時はログインIDとパスワードを両方入力してください。")
                elif auth_login_id and not auth_password:
                    errors.append("新規連携時はログインIDとパスワードを両方入力してください。")
                else:
                    if User.objects.filter(username=auth_login_id).exists():
                        errors.append("このログインIDはすでに使用されています。")
                    else:
                        linked_user = User.objects.create_user(
                            username=auth_login_id,
                            password=auth_password,
                        )
                        member.user = linked_user
                        member.save(update_fields=["user"])
                        changed = True

            if errors:
                row_errors[member.id] = errors
            elif changed:
                updated_count += 1

        if not row_errors:
            status_message = f"{updated_count}件のログイン情報を更新しました。"
        else:
            status_message = "入力内容にエラーがあります。該当行を修正してください。"
        current_page_number = str(page_obj.number)

    member_rows = []
    for member in page_obj.object_list:
        member_rows.append(
            {
                "member": member,
                "login_input": row_login_inputs.get(member.id, ""),
                "errors": row_errors.get(member.id, []),
            }
        )

    return render(
        request,
        "dashboard/member_auth_bulk_settings.html",
        {
            "page_obj": page_obj,
            "paginator": paginator,
            "status_message": status_message,
            "member_rows": member_rows,
            "current_page_number": str(current_page_number),
        },
    )
