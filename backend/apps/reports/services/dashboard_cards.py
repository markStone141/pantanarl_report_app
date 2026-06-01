from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import Department
from apps.common.dashboard_snapshot import build_member_rows, build_submission_snapshot
from apps.common.target_periods import current_active_period
from apps.common.report_metrics import (
    SPLIT_COUNT_CODES,
    collect_actual_totals,
    format_metric_triples,
    period_status as calc_period_status,
)
from apps.dairymetrics.models import MemberDailyMetricEntry
from apps.targets.models import MonthTargetMetricValue, PeriodTargetMetricValue, TargetMetric


def format_amount_text(value):
    if isinstance(value, int):
        return f"{value:,}"
    return value


def build_report_dashboard_cards_context():
    today = timezone.localdate()
    target_departments = list(
        Department.objects.filter(is_active=True).order_by("code").values_list("code", "name")
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
        row["amount_text"] = format_amount_text(row.get("amount"))

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

    current_period = current_active_period(target_date=today)

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
        period_start = None
        period_end = None
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
    departments_by_code = {department.code: department for department in Department.objects.filter(code__in=target_codes)}
    for code, _ in target_departments:
        department = departments_by_code.get(code)
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
        member_rows = build_member_rows(member_totals=member_totals, codes=[code])
        for member_row in member_rows:
            member_row["amount_text"] = format_amount_text(member_row.get("amount", 0))
        kpi_cards.append(
            {
                "code": code,
                "title": label,
                "count": daily_totals[code]["count"],
                "amount": daily_totals[code]["amount"],
                "amount_text": format_amount_text(daily_totals[code]["amount"]),
                "has_split_counts": code in SPLIT_COUNT_CODES,
                "cs_count": daily_totals[code]["cs_count"],
                "refugee_count": daily_totals[code]["refugee_count"],
                "members": member_rows,
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
