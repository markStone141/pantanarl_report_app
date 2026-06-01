from __future__ import annotations

from datetime import timedelta

from apps.common.target_periods import current_active_period
from apps.common.report_metrics import (
    collect_actual_totals,
    collect_adjustment_totals,
    metric_detail_rows,
    period_status as calc_period_status,
)
from apps.targets.models import MonthTargetMetricValue, PeriodTargetMetricValue, TargetMetric


def collect_metrics_by_code(*, target_codes):
    metrics = (
        TargetMetric.objects.filter(department__code__in=target_codes, is_active=True)
        .select_related("department")
        .order_by("department__code", "display_order", "id")
    )
    metrics_by_code = {code: [] for code in target_codes}
    for metric in metrics:
        metrics_by_code.setdefault(metric.department.code, []).append(metric)
    return metrics_by_code


def _collect_target_values_by_code(*, target_codes, queryset):
    values_by_code = {code: {} for code in target_codes}
    for row in queryset.values("department__code", "metric_id", "value"):
        values_by_code[row["department__code"]][row["metric_id"]] = row["value"]
    return values_by_code


def build_target_scope_snapshot(*, target_date, target_codes, metrics_by_code):
    month_start = target_date.replace(day=1)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

    month_target_values_by_code = _collect_target_values_by_code(
        target_codes=target_codes,
        queryset=MonthTargetMetricValue.objects.filter(
            target_month=month_start,
            metric__is_active=True,
            department__code__in=target_codes,
        ).order_by("department__code", "metric__display_order", "id"),
    )

    current_period = current_active_period(target_date=target_date)

    if current_period:
        period_target_values_by_code = _collect_target_values_by_code(
            target_codes=target_codes,
            queryset=PeriodTargetMetricValue.objects.filter(
                period=current_period,
                metric__is_active=True,
                department__code__in=target_codes,
            ).order_by("department__code", "metric__display_order", "id"),
        )
        period_start = current_period.start_date
        period_end = current_period.end_date
        period_label = current_period.name
        period_range = (
            f"{current_period.start_date.month}/{current_period.start_date.day}"
            f"～{current_period.end_date.month}/{current_period.end_date.day}"
        )
        period_status = calc_period_status(
            today=target_date,
            start_date=current_period.start_date,
            end_date=current_period.end_date,
        )
    else:
        period_target_values_by_code = {code: {} for code in target_codes}
        period_start = None
        period_end = None
        period_label = "-"
        period_range = "-"
        period_status = "-"

    month_status = (
        "active"
        if month_start == target_date.replace(day=1)
        else ("planned" if month_start > target_date.replace(day=1) else "finished")
    )

    month_actual_totals_by_code = collect_actual_totals(
        start_date=month_start,
        end_date=month_end,
        target_codes=target_codes,
        include_adjustments=True,
    )
    month_adjustment_totals_by_code = collect_adjustment_totals(
        start_date=month_start,
        end_date=month_end,
        target_codes=target_codes,
    )

    if period_start and period_end:
        period_actual_totals_by_code = collect_actual_totals(
            start_date=period_start,
            end_date=period_end,
            target_codes=target_codes,
            include_adjustments=True,
        )
        period_adjustment_totals_by_code = collect_adjustment_totals(
            start_date=period_start,
            end_date=period_end,
            target_codes=target_codes,
        )
    else:
        period_actual_totals_by_code = {
            code: {"count": 0, "amount": 0, "cs_count": 0, "refugee_count": 0}
            for code in target_codes
        }
        period_adjustment_totals_by_code = {
            code: {"count": 0, "amount": 0, "cs_count": 0, "refugee_count": 0}
            for code in target_codes
        }

    metric_detail_by_code = {}
    for code in target_codes:
        metric_detail_by_code[code] = {
            "month": metric_detail_rows(
                metrics=metrics_by_code.get(code, []),
                target_values=month_target_values_by_code.get(code, {}),
                actual_totals=month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
            ),
            "period": metric_detail_rows(
                metrics=metrics_by_code.get(code, []),
                target_values=period_target_values_by_code.get(code, {}),
                actual_totals=period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
            ),
        }

    return {
        "month_start": month_start,
        "month_end": month_end,
        "month_status": month_status,
        "month_target_values_by_code": month_target_values_by_code,
        "month_actual_totals_by_code": month_actual_totals_by_code,
        "month_adjustment_totals_by_code": month_adjustment_totals_by_code,
        "current_period": current_period,
        "period_label": period_label,
        "period_range": period_range,
        "period_status": period_status,
        "period_start": period_start,
        "period_end": period_end,
        "period_target_values_by_code": period_target_values_by_code,
        "period_actual_totals_by_code": period_actual_totals_by_code,
        "period_adjustment_totals_by_code": period_adjustment_totals_by_code,
        "metric_detail_by_code": metric_detail_by_code,
    }
