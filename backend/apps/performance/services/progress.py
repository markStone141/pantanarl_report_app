from __future__ import annotations

from datetime import date

from django.db.models import Sum

from apps.dairymetrics.models import MetricAdjustment, WVMetricCancellation
from apps.targets.models import (
    DepartmentMonthTarget,
    DepartmentPeriodTarget,
    MonthTargetMetricValue,
    Period,
    PeriodTargetMetricValue,
)


def resolve_month_target_amounts_by_code(*, departments, target_month: date) -> dict[str, int]:
    target_codes = [department.code for department in departments]
    metric_rows = (
        MonthTargetMetricValue.objects.filter(
            department__code__in=target_codes,
            target_month=target_month,
            metric__code="amount",
        )
        .values("department__code", "value")
    )
    target_map = {row["department__code"]: int(row["value"] or 0) for row in metric_rows}
    fallback_rows = (
        DepartmentMonthTarget.objects.filter(
            department__code__in=target_codes,
            target_month=target_month,
        )
        .values("department__code", "target_amount")
    )
    for row in fallback_rows:
        target_map.setdefault(row["department__code"], int(row["target_amount"] or 0))
    return target_map


def resolve_period_target_amounts_by_code(*, departments, period: Period | None) -> dict[str, int]:
    if not period:
        return {}
    target_codes = [department.code for department in departments]
    metric_rows = (
        PeriodTargetMetricValue.objects.filter(
            department__code__in=target_codes,
            period=period,
            metric__code="amount",
        )
        .values("department__code", "value")
    )
    target_map = {row["department__code"]: int(row["value"] or 0) for row in metric_rows}
    fallback_rows = (
        DepartmentPeriodTarget.objects.filter(
            department__code__in=target_codes,
            period=period,
        )
        .values("department__code", "target_amount")
    )
    for row in fallback_rows:
        target_map.setdefault(row["department__code"], int(row["target_amount"] or 0))
    return target_map


def collect_adjustment_amounts_by_codes(*, target_codes, start_date: date, end_date: date) -> dict[str, int]:
    if not target_codes:
        return {}
    rows = (
        MetricAdjustment.objects.filter(
            department__code__in=target_codes,
            target_date__range=(start_date, end_date),
        )
        .values("department__code")
        .annotate(
            support_amount_total=Sum("support_amount"),
            return_postal_amount_total=Sum("return_postal_amount"),
            return_qr_amount_total=Sum("return_qr_amount"),
        )
    )
    adjustment_amounts = {
        row["department__code"]: (
            int(row["support_amount_total"] or 0)
            + int(row["return_postal_amount_total"] or 0)
            + int(row["return_qr_amount_total"] or 0)
        )
        for row in rows
    }
    cancellation_rows = (
        WVMetricCancellation.objects.filter(
            department__code__in=target_codes,
            target_date__range=(start_date, end_date),
        )
        .values("department__code")
        .annotate(support_amount_total=Sum("support_amount"))
    )
    for row in cancellation_rows:
        code = row["department__code"]
        adjustment_amounts[code] = int(adjustment_amounts.get(code) or 0) - int(row["support_amount_total"] or 0)
    return adjustment_amounts


def progress_rate(actual: int, target: int) -> float | None:
    if target <= 0:
        return None
    return round((actual / target) * 100, 1)


def build_progress_card(*, label, actual_amount, target_amount, summary_text, base_actual_amount=0, adjustment_amount=0):
    rate = progress_rate(actual_amount, target_amount)
    remaining_amount = max(int(target_amount or 0) - int(actual_amount or 0), 0)
    base_actual_amount = int(base_actual_amount or 0)
    adjustment_amount = int(adjustment_amount or 0)
    target_amount = int(target_amount or 0)
    if target_amount > 0:
        capped_base_amount = min(base_actual_amount, target_amount)
        capped_adjustment_amount = min(max(adjustment_amount, 0), max(target_amount - capped_base_amount, 0))
        remaining_chart_amount = max(target_amount - capped_base_amount - capped_adjustment_amount, 0)
        chart_values = [capped_base_amount, capped_adjustment_amount, remaining_chart_amount]
    else:
        chart_values = [0, 0, 100]
    return {
        "label": label,
        "actual_amount": actual_amount,
        "actual_amount_text": f"{actual_amount:,}円",
        "base_actual_amount_text": f"{base_actual_amount:,}円",
        "adjustment_amount_text": f"{adjustment_amount:,}円",
        "target_amount": target_amount,
        "target_amount_text": f"{target_amount:,}円",
        "remaining_amount_text": f"{remaining_amount:,}円",
        "rate": rate,
        "rate_text": "-" if rate is None else f"{rate}%",
        "chart_values": chart_values,
        "summary_text": summary_text,
    }


def build_contribution_summary(*, member_actual_amount, department_actual_amount):
    department_amount = int(department_actual_amount or 0)
    member_amount = int(member_actual_amount or 0)
    if department_amount <= 0:
        return {
            "rate": None,
            "rate_text": "-",
            "detail_text": "全体実績がまだありません。",
        }
    rate = round((member_amount / department_amount) * 100, 1)
    return {
        "rate": rate,
        "rate_text": f"{rate}%",
        "detail_text": f"{member_amount:,}円 / {department_amount:,}円",
    }


def month_end(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1) - date.resolution
    return date(month_start.year, month_start.month + 1, 1) - date.resolution


def adjustment_totals_dict_from_queryset(*, queryset) -> dict[str, int]:
    totals = queryset.aggregate(
        result_count_total=Sum("result_count"),
        support_amount_total=Sum("support_amount"),
        return_postal_count_total=Sum("return_postal_count"),
        return_postal_amount_total=Sum("return_postal_amount"),
        return_qr_count_total=Sum("return_qr_count"),
        return_qr_amount_total=Sum("return_qr_amount"),
        cs_count_total=Sum("cs_count"),
        refugee_count_total=Sum("refugee_count"),
    )
    return {
        "result_count": int(totals["result_count_total"] or 0),
        "support_amount": int(totals["support_amount_total"] or 0),
        "return_postal_count": int(totals["return_postal_count_total"] or 0),
        "return_postal_amount": int(totals["return_postal_amount_total"] or 0),
        "return_qr_count": int(totals["return_qr_count_total"] or 0),
        "return_qr_amount": int(totals["return_qr_amount_total"] or 0),
        "cs_count": int(totals["cs_count_total"] or 0),
        "refugee_count": int(totals["refugee_count_total"] or 0),
    }


def sum_adjustment_amount(*, member=None, department=None, start_date: date, end_date: date) -> int:
    queryset = MetricAdjustment.objects.filter(target_date__range=(start_date, end_date))
    if member is not None:
        queryset = queryset.filter(member=member)
    if department is not None:
        queryset = queryset.filter(department=department)
    totals = queryset.aggregate(
        support_amount_total=Sum("support_amount"),
        return_postal_amount_total=Sum("return_postal_amount"),
        return_qr_amount_total=Sum("return_qr_amount"),
    )
    adjustment_amount = (
        int(totals["support_amount_total"] or 0)
        + int(totals["return_postal_amount_total"] or 0)
        + int(totals["return_qr_amount_total"] or 0)
    )
    cancellation_queryset = WVMetricCancellation.objects.filter(target_date__range=(start_date, end_date))
    if member is not None:
        cancellation_queryset = cancellation_queryset.filter(member=member)
    if department is not None:
        cancellation_queryset = cancellation_queryset.filter(department=department)
    cancellation_totals = cancellation_queryset.aggregate(support_amount_total=Sum("support_amount"))
    return adjustment_amount - int(cancellation_totals["support_amount_total"] or 0)
