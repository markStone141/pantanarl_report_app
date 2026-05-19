from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Member
from apps.targets.models import (
    DepartmentMonthTarget,
    DepartmentPeriodTarget,
    MonthTargetMetricValue,
    Period,
    PeriodTargetMetricValue,
)

from apps.dairymetrics.models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_member_final_actual_totals,
)


RANKING_METRIC_OPTIONS = [
    {"key": "conversion_rate", "label": "決済率", "unit": "%"},
    {"key": "communication_rate", "label": "コミュニケーション率", "unit": "%"},
    {"key": "approach_count", "label": "合計アプローチ数", "unit": ""},
    {"key": "communication_count", "label": "合計コミュニケーション数", "unit": ""},
    {"key": "average_amount_per_active_day", "label": "1稼働あたりの平均金額", "unit": "円"},
    {"key": "average_amount_per_decision", "label": "1決済あたりの平均金額", "unit": "円"},
    {"key": "support_amount", "label": "合計決済金額", "unit": "円"},
    {"key": "decision_count", "label": "合計件数", "unit": ""},
    {"key": "increase_count", "label": "増額件数", "unit": ""},
    {"key": "increase_amount", "label": "増額金額", "unit": "円"},
    {"key": "return_count", "label": "戻り件数", "unit": ""},
    {"key": "return_amount", "label": "戻り金額", "unit": "円"},
]


@dataclass(frozen=True)
class MetricsV2Scope:
    scope: str
    label: str
    start_date: date
    end_date: date
    month_start: date | None = None
    period: Period | None = None


def _count_value(department_code: str, totals: dict) -> int:
    if department_code == "WV":
        return int(totals.get("cs_count") or 0) + int(totals.get("refugee_count") or 0) + int(totals.get("result_count") or 0)
    return int(totals.get("result_count") or 0)


def _return_count_value(totals: dict) -> int:
    return int(totals.get("return_postal_count") or 0) + int(totals.get("return_qr_count") or 0)


def _return_amount_value(totals: dict) -> int:
    return int(totals.get("return_postal_amount") or 0) + int(totals.get("return_qr_amount") or 0)


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 1)


def _format_percentage(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def _safe_average(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 1)


def _format_number(value: float | int | None, unit: str = "") -> str:
    if value is None:
        return "-"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "円":
        return f"{int(round(value)):,}円"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}{unit}"
    return f"{int(value):,}{unit}"


def resolve_metrics_v2_scope(
    *,
    today: date,
    scope: str,
    requested_month: date | None = None,
    requested_period: Period | None = None,
    requested_start_date: date | None = None,
    requested_end_date: date | None = None,
) -> MetricsV2Scope:
    if scope == "month":
        month_start = requested_month or today.replace(day=1)
        month_end = month_start.replace(day=monthrange(month_start.year, month_start.month)[1])
        return MetricsV2Scope(
            scope="month",
            label=month_start.strftime("%Y/%m"),
            start_date=month_start,
            end_date=month_end,
            month_start=month_start,
        )
    if scope == "period" and requested_period:
        return MetricsV2Scope(
            scope="period",
            label=requested_period.name,
            start_date=requested_period.start_date,
            end_date=requested_period.end_date,
            period=requested_period,
        )
    if scope == "custom":
        start_date = requested_start_date or (today - timedelta(days=29))
        end_date = requested_end_date or today
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return MetricsV2Scope(
            scope="custom",
            label=f"{start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}",
            start_date=start_date,
            end_date=end_date,
        )
    return MetricsV2Scope(
        scope="recent",
        label="過去30日間",
        start_date=today - timedelta(days=29),
        end_date=today,
    )


def _department_target_amount_for_scope(*, department, scope: MetricsV2Scope) -> int:
    if scope.scope == "month" and scope.month_start:
        value = (
            MonthTargetMetricValue.objects.filter(
                department=department,
                target_month=scope.month_start,
                metric__code="amount",
            )
            .select_related("metric")
            .first()
        )
        if value:
            return int(value.value or 0)
        legacy = DepartmentMonthTarget.objects.filter(department=department, target_month=scope.month_start).first()
        return int(legacy.target_amount if legacy else 0)
    if scope.scope == "period" and scope.period:
        value = (
            PeriodTargetMetricValue.objects.filter(
                department=department,
                period=scope.period,
                metric__code="amount",
            )
            .select_related("metric")
            .first()
        )
        if value:
            return int(value.value or 0)
        legacy = DepartmentPeriodTarget.objects.filter(department=department, period=scope.period).first()
        return int(legacy.target_amount if legacy else 0)
    return int(
        DepartmentDailyMetricSummary.objects.filter(
            department=department,
            entry_date__range=(scope.start_date, scope.end_date),
        ).aggregate(total=Sum("daily_target_amount"))["total"]
        or 0
    )


def _member_target_amount_for_scope(*, member, department, scope: MetricsV2Scope) -> int:
    if scope.scope == "month" and scope.month_start:
        target = MemberMonthMetricTarget.objects.filter(
            member=member,
            department=department,
            target_month=scope.month_start,
        ).first()
        return int(target.target_amount if target else 0)
    if scope.scope == "period" and scope.period:
        target = MemberPeriodMetricTarget.objects.filter(
            member=member,
            department=department,
            period=scope.period,
        ).first()
        return int(target.target_amount if target else 0)
    return int(
        MemberDailyMetricEntry.objects.filter(
            member=member,
            department=department,
            entry_date__range=(scope.start_date, scope.end_date),
        ).aggregate(total=Sum("daily_target_amount"))["total"]
        or 0
    )


def _active_day_count(*, member=None, department, start_date: date, end_date: date) -> int:
    queryset = MemberDailyMetricEntry.objects.filter(
        department=department,
        entry_date__range=(start_date, end_date),
    )
    if member is not None:
        queryset = queryset.filter(member=member)
    return queryset.values("entry_date").distinct().count()


def _increase_totals(*, member=None, department, start_date: date, end_date: date) -> dict:
    queryset = MetricAdjustment.objects.filter(
        department=department,
        target_date__range=(start_date, end_date),
        source_type=MetricAdjustment.SOURCE_INCREASE,
    )
    if member is not None:
        queryset = queryset.filter(member=member)
    aggregated = queryset.aggregate(total_count=Sum("result_count"), total_amount=Sum("support_amount"))
    return {
        "count": int(aggregated["total_count"] or 0),
        "amount": int(aggregated["total_amount"] or 0),
    }


def _build_summary_cards(*, title_prefix: str, department_code: str, totals: dict, target_amount: int, active_days: int) -> dict:
    decision_count = _count_value(department_code, totals)
    support_amount = int(totals.get("support_amount") or 0)
    approach_count = int(totals.get("approach_count") or 0)
    communication_count = int(totals.get("communication_count") or 0)
    conversion_rate = _percentage(decision_count, communication_count)
    communication_rate = _percentage(communication_count, approach_count)
    return {
        "title_prefix": title_prefix,
        "rates": [
            {
                "key": "conversion",
                "label": "決済率",
                "value": _format_percentage(conversion_rate),
                "helper": f"件数 {decision_count:,} / CM {communication_count:,}",
                "chart_data": [decision_count, max(communication_count - decision_count, 0)],
            },
            {
                "key": "communication",
                "label": "コミュニケーション率",
                "value": _format_percentage(communication_rate),
                "helper": f"CM {communication_count:,} / AP {approach_count:,}",
                "chart_data": [communication_count, max(approach_count - communication_count, 0)],
            },
        ],
        "averages": [
            {"label": "1稼働あたりの平均AP", "value": _format_number(_safe_average(approach_count, active_days))},
            {"label": "1稼働あたりの平均CM", "value": _format_number(_safe_average(communication_count, active_days))},
            {"label": "1稼働あたりの平均件数", "value": _format_number(_safe_average(decision_count, active_days))},
            {"label": "1稼働あたりの平均金額", "value": _format_number(_safe_average(support_amount, active_days), "円")},
            {"label": "1決済あたりの平均金額", "value": _format_number(_safe_average(support_amount, decision_count), "円")},
            {"label": "目標進捗", "value": _format_percentage(_percentage(support_amount, target_amount))},
        ],
        "totals": {
            "support_amount": support_amount,
            "decision_count": decision_count,
            "approach_count": approach_count,
            "communication_count": communication_count,
            "return_count": _return_count_value(totals),
            "return_amount": _return_amount_value(totals),
        },
    }


def _build_distribution_cards(*, transaction_queryset):
    age_labels = dict(MemberMetricTransaction.AGE_BAND_CHOICES)
    gender_labels = dict(MemberMetricTransaction.GENDER_CHOICES)
    nationality_labels = dict(MemberMetricTransaction.NATIONALITY_CHOICES)

    age_counts = defaultdict(int)
    age_amounts = defaultdict(int)
    gender_counts = defaultdict(int)
    gender_amounts = defaultdict(int)
    nationality_counts = defaultdict(int)
    nationality_amounts = defaultdict(int)

    for tx in transaction_queryset:
        amount = int(tx.support_amount or 0)
        age_counts[tx.age_band] += 1
        age_amounts[tx.age_band] += amount
        gender_counts[tx.gender] += 1
        gender_amounts[tx.gender] += amount
        nationality_counts[tx.nationality_type] += 1
        nationality_amounts[tx.nationality_type] += amount

    def pack(title: str, labels_map: dict, counts: dict, amounts: dict):
        ordered_keys = [key for key, _label in labels_map.items() if counts.get(key) or amounts.get(key)]
        if not ordered_keys:
            ordered_keys = list(labels_map.keys())
        labels = [labels_map[key] for key in ordered_keys]
        count_values = [int(counts.get(key) or 0) for key in ordered_keys]
        avg_amount_values = [
            round((amounts.get(key) or 0) / count_values[index], 1) if count_values[index] > 0 else None
            for index, key in enumerate(ordered_keys)
        ]
        total = sum(count_values)
        rows = []
        for index, label in enumerate(labels):
            count_value = count_values[index]
            percentage = round((count_value / total) * 100, 1) if total > 0 else 0
            rows.append(
                {
                    "label": label,
                    "count_text": f"{count_value:,}件",
                    "percent_text": f"{percentage:.1f}%",
                }
            )
        return {
            "title": title,
            "labels": labels,
            "counts": count_values,
            "total_text": f"{total:,}件",
            "has_data": total > 0,
            "avg_amounts": avg_amount_values,
            "rows": rows,
        }

    cards = [
        pack("年代別決済比率", age_labels, age_counts, age_amounts),
        pack("男女比", gender_labels, gender_counts, gender_amounts),
        pack("国籍比", nationality_labels, nationality_counts, nationality_amounts),
    ]
    average_amount_comparison = {
        "age": {"title": "年代別の平均金額", "labels": cards[0]["labels"], "values": cards[0]["avg_amounts"]},
        "gender": {"title": "男女別の平均金額", "labels": cards[1]["labels"], "values": cards[1]["avg_amounts"]},
        "nationality": {"title": "国籍別の平均金額", "labels": cards[2]["labels"], "values": cards[2]["avg_amounts"]},
    }
    return cards, average_amount_comparison


def _build_period_totals_series(*, department, member=None, periods):
    labels = []
    amounts = []
    counts = []
    for period in periods:
        if member is None:
            totals = collect_department_final_actual_totals(department, period.start_date, period.end_date, include_adjustments=True)
        else:
            totals = collect_member_final_actual_totals(member, department, period.start_date, period.end_date, include_adjustments=True)
        labels.append(period.name)
        amounts.append(int(totals.get("support_amount") or 0))
        counts.append(_count_value(department.code, totals))
    return {"labels": labels, "amounts": amounts, "counts": counts, "has_data": any(amounts) or any(counts)}


def _build_month_totals_series(*, department, member=None, reference_month: date):
    month_starts = []
    cursor = reference_month.replace(day=1)
    for _index in range(6):
        month_starts.append(cursor)
        previous_month = (cursor.replace(day=1) - timedelta(days=1)).replace(day=1)
        cursor = previous_month
    month_starts.reverse()

    labels = []
    amounts = []
    counts = []
    for month_start in month_starts:
        month_end = month_start.replace(day=monthrange(month_start.year, month_start.month)[1])
        if member is None:
            totals = collect_department_final_actual_totals(department, month_start, month_end, include_adjustments=True)
        else:
            totals = collect_member_final_actual_totals(member, department, month_start, month_end, include_adjustments=True)
        labels.append(month_start.strftime("%Y/%m"))
        amounts.append(int(totals.get("support_amount") or 0))
        counts.append(_count_value(department.code, totals))
    return {"labels": labels, "amounts": amounts, "counts": counts, "has_data": any(amounts) or any(counts)}


def _member_metric_row(*, member, department, scope: MetricsV2Scope):
    totals = collect_member_final_actual_totals(member, department, scope.start_date, scope.end_date, include_adjustments=True)
    active_days = _active_day_count(member=member, department=department, start_date=scope.start_date, end_date=scope.end_date)
    decision_count = _count_value(department.code, totals)
    support_amount = int(totals.get("support_amount") or 0)
    increase_totals = _increase_totals(member=member, department=department, start_date=scope.start_date, end_date=scope.end_date)
    return {
        "member": member,
        "metrics": {
            "conversion_rate": _percentage(decision_count, int(totals.get("communication_count") or 0)) or 0,
            "communication_rate": _percentage(int(totals.get("communication_count") or 0), int(totals.get("approach_count") or 0)) or 0,
            "approach_count": int(totals.get("approach_count") or 0),
            "communication_count": int(totals.get("communication_count") or 0),
            "average_amount_per_active_day": _safe_average(support_amount, active_days) or 0,
            "average_amount_per_decision": _safe_average(support_amount, decision_count) or 0,
            "support_amount": support_amount,
            "decision_count": decision_count,
            "increase_count": increase_totals["count"],
            "increase_amount": increase_totals["amount"],
            "return_count": _return_count_value(totals),
            "return_amount": _return_amount_value(totals),
        },
    }


def _build_ranking_payload(*, department, scope: MetricsV2Scope):
    members = list(Member.objects.active().filter(department_links__department=department).distinct().order_by("name"))
    rows = [_member_metric_row(member=member, department=department, scope=scope) for member in members]
    metric_map = {}
    for option in RANKING_METRIC_OPTIONS:
        ranked_rows = sorted(rows, key=lambda item: item["metrics"][option["key"]], reverse=True)
        metric_map[option["key"]] = {
            "label": option["label"],
            "unit": option["unit"],
            "labels": [row["member"].name for row in ranked_rows],
            "values": [row["metrics"][option["key"]] for row in ranked_rows],
            "detail_urls": [reverse("dairymetrics_member_dashboard", args=[row["member"].id]) for row in ranked_rows],
            "rows": [
                {
                    "member_name": row["member"].name,
                    "member_id": row["member"].id,
                    "value_text": _format_number(row["metrics"][option["key"]], option["unit"]),
                    "detail_url": reverse("dairymetrics_member_dashboard", args=[row["member"].id]),
                }
                for row in ranked_rows
            ],
        }
    return {
        "default_metric": "support_amount",
        "options": RANKING_METRIC_OPTIONS,
        "metric_map": metric_map,
    }


def build_metrics_v2_dashboard_payload(
    *,
    department,
    scope: MetricsV2Scope,
    member=None,
) -> dict:
    overall_totals = collect_department_final_actual_totals(department, scope.start_date, scope.end_date, include_adjustments=True)
    overall_target_amount = _department_target_amount_for_scope(department=department, scope=scope)
    overall_active_days = _active_day_count(department=department, start_date=scope.start_date, end_date=scope.end_date)

    personal_totals = None
    personal_target_amount = 0
    personal_active_days = 0
    if member is not None:
        personal_totals = collect_member_final_actual_totals(member, department, scope.start_date, scope.end_date, include_adjustments=True)
        personal_target_amount = _member_target_amount_for_scope(member=member, department=department, scope=scope)
        personal_active_days = _active_day_count(member=member, department=department, start_date=scope.start_date, end_date=scope.end_date)

    transaction_queryset = MemberMetricTransaction.objects.filter(
        entry__department=department,
        entry__entry_date__range=(scope.start_date, scope.end_date),
    ).select_related("entry")
    if member is not None:
        transaction_queryset = transaction_queryset.filter(entry__member=member)

    distributions, average_amount_comparison = _build_distribution_cards(transaction_queryset=transaction_queryset)

    reference_month = scope.month_start or scope.end_date.replace(day=1)
    available_periods = list(Period.objects.filter(end_date__lte=scope.end_date).order_by("-end_date", "-start_date", "-id")[:6])
    available_periods.reverse()

    return {
        "scope": scope,
        "overall_summary": _build_summary_cards(
            title_prefix=f"{department.name} 全体",
            department_code=department.code,
            totals=overall_totals,
            target_amount=overall_target_amount,
            active_days=overall_active_days,
        ),
        "personal_summary": (
            _build_summary_cards(
                title_prefix=f"{member.name} さん",
                department_code=department.code,
                totals=personal_totals,
                target_amount=personal_target_amount,
                active_days=personal_active_days,
            )
            if member is not None and personal_totals is not None
            else None
        ),
        "month_history": _build_month_totals_series(
            department=department,
            member=member,
            reference_month=reference_month,
        ),
        "period_history": _build_period_totals_series(
            department=department,
            member=member,
            periods=available_periods,
        ),
        "distribution_cards": distributions,
        "average_amount_comparison": average_amount_comparison,
        "ranking": _build_ranking_payload(department=department, scope=scope),
    }
