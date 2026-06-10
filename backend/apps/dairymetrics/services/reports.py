from __future__ import annotations

from django.db.models import Count, Sum

from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction, MetricAdjustment
from apps.dairymetrics.services.final_actuals import (
    ADJUSTMENT_METRIC_FIELDS,
    ENTRY_METRIC_FIELDS,
    collect_department_final_actual_totals,
    collect_member_final_actual_totals_by_ids,
    merge_final_actual_totals,
    zero_final_actual_totals,
)
from apps.dairymetrics.services.metrics_v2 import (
    _count_value,
    _department_target_amount_for_scope,
    _format_number,
    _format_percentage,
    _percentage,
    _return_amount_value,
    _return_count_value,
    _ranking_members,
    _safe_average,
    _wv_count_breakdown_text,
)


def _format_diff(value: int, *, unit: str) -> str:
    if value >= 0:
        return f"+{value:,}{unit}"
    return f"あと {abs(value):,}{unit}"


def _daily_report_rows(*, department, scope):
    daily_totals = {}
    transactions_by_date = {}

    entry_annotations = {f"sum_{field}": Sum(field) for field in ENTRY_METRIC_FIELDS}
    entry_rows = (
        MemberDailyMetricEntry.objects.filter(
            department=department,
            entry_date__range=(scope.start_date, scope.end_date),
        )
        .values("entry_date")
        .annotate(**entry_annotations)
        .order_by("entry_date")
    )
    for row in entry_rows:
        entry_date = row["entry_date"]
        totals = daily_totals.setdefault(
            entry_date,
            {"entry": zero_final_actual_totals(), "adjustment": zero_final_actual_totals()},
        )
        for field in ENTRY_METRIC_FIELDS:
            totals["entry"][field] = int(row.get(f"sum_{field}") or 0)

    adjustment_annotations = {f"sum_{field}": Sum(field) for field in ADJUSTMENT_METRIC_FIELDS}
    adjustment_rows = (
        MetricAdjustment.objects.filter(
            department=department,
            target_date__range=(scope.start_date, scope.end_date),
        )
        .values("target_date")
        .annotate(**adjustment_annotations)
        .order_by("target_date")
    )
    for row in adjustment_rows:
        target_date = row["target_date"]
        totals = daily_totals.setdefault(
            target_date,
            {"entry": zero_final_actual_totals(), "adjustment": zero_final_actual_totals()},
        )
        for field in ADJUSTMENT_METRIC_FIELDS:
            totals["adjustment"][field] = int(row.get(f"sum_{field}") or 0)

    transactions = (
        MemberMetricTransaction.objects.filter(
            entry__department=department,
            entry__entry_date__range=(scope.start_date, scope.end_date),
        )
        .select_related("entry", "entry__member")
        .order_by("-entry__entry_date", "created_at", "id")
    )
    for transaction in transactions:
        entry_date = transaction.entry.entry_date
        transaction_type = transaction.get_wv_result_type_display() if department.code == "WV" and transaction.wv_result_type else "決済"
        transactions_by_date.setdefault(entry_date, []).append(
            {
                "member_name": transaction.entry.member.name,
                "amount_text": _format_number(int(transaction.support_amount or 0), "円"),
                "type_text": transaction_type,
                "age_text": transaction.get_age_band_display(),
                "gender_text": transaction.get_gender_display(),
                "nationality_text": transaction.get_nationality_type_display(),
                "location_text": transaction.location or transaction.entry.location_name or "-",
                "comment": transaction.comment,
            }
        )

    rows = []
    for entry_date, totals in sorted(daily_totals.items(), reverse=True):
        merged = merge_final_actual_totals(totals["entry"], totals["adjustment"])
        decision_count = _count_value(department.code, merged)
        amount = int(merged.get("support_amount") or 0)
        rows.append(
            {
                "date_text": entry_date.strftime("%Y/%m/%d"),
                "amount_value": amount,
                "count_text": _format_number(decision_count),
                "amount_text": _format_number(amount, "円"),
                "approach_text": _format_number(int(merged.get("approach_count") or 0)),
                "communication_text": _format_number(int(merged.get("communication_count") or 0)),
                "breakdown_text": _wv_count_breakdown_text(merged, include_total=True) if department.code == "WV" else "",
                "transactions": transactions_by_date.get(entry_date, []),
            }
        )
    return rows


def _member_report_rows(*, department, scope):
    members = _ranking_members(department=department, scope=scope)
    member_ids = [member.id for member in members]
    totals_by_member_id = collect_member_final_actual_totals_by_ids(
        member_ids=member_ids,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
        include_adjustments=True,
    )
    base_totals_by_member_id = collect_member_final_actual_totals_by_ids(
        member_ids=member_ids,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
        include_adjustments=False,
    )
    active_day_rows = (
        MemberDailyMetricEntry.objects.filter(
            member_id__in=member_ids,
            department=department,
            entry_date__range=(scope.start_date, scope.end_date),
        )
        .values("member_id")
        .annotate(active_days=Count("entry_date", distinct=True))
    )
    active_days_by_member_id = {row["member_id"]: int(row["active_days"] or 0) for row in active_day_rows}

    rows = []
    for member in members:
        totals = totals_by_member_id.get(member.id, zero_final_actual_totals())
        base_totals = base_totals_by_member_id.get(member.id, zero_final_actual_totals())
        decision_count = _count_value(department.code, totals)
        base_decision_count = _count_value(department.code, base_totals)
        amount = int(totals.get("support_amount") or 0)
        approach_count = int(totals.get("approach_count") or 0)
        communication_count = int(totals.get("communication_count") or 0)
        base_approach_count = int(base_totals.get("approach_count") or 0)
        base_communication_count = int(base_totals.get("communication_count") or 0)
        active_days = active_days_by_member_id.get(member.id, 0)
        communication_rate = _percentage(base_communication_count, base_approach_count)
        conversion_rate = _percentage(base_decision_count, base_communication_count)
        average_amount_per_decision = _safe_average(amount, decision_count)
        average_amount_per_active_day = _safe_average(amount, active_days)
        rows.append(
            {
                "member_name": member.name,
                "member_sort_value": member.name,
                "count_value": decision_count,
                "count_text": _format_number(decision_count),
                "amount_value": amount,
                "amount_text": _format_number(amount, "円"),
                "approach_value": approach_count,
                "approach_text": _format_number(approach_count),
                "communication_value": communication_count,
                "communication_text": _format_number(communication_count),
                "communication_rate_value": communication_rate or 0,
                "communication_rate_text": _format_percentage(communication_rate),
                "conversion_rate_value": conversion_rate or 0,
                "conversion_rate_text": _format_percentage(conversion_rate),
                "average_amount_per_decision_value": average_amount_per_decision or 0,
                "average_amount_per_decision_text": _format_number(average_amount_per_decision, "円"),
                "average_amount_per_active_day_value": average_amount_per_active_day or 0,
                "average_amount_per_active_day_text": _format_number(average_amount_per_active_day, "円"),
                "active_days_value": active_days,
                "active_days_text": _format_number(active_days),
                "breakdown_text": _wv_count_breakdown_text(totals) if department.code == "WV" else "",
            }
        )
    return sorted(rows, key=lambda row: row["member_name"])


def build_metrics_scope_report(*, department, scope):
    final_totals = collect_department_final_actual_totals(
        department,
        scope.start_date,
        scope.end_date,
        include_adjustments=True,
    )
    base_totals = collect_department_final_actual_totals(
        department,
        scope.start_date,
        scope.end_date,
        include_adjustments=False,
    )
    target_amount = _department_target_amount_for_scope(department=department, scope=scope)

    decision_count = _count_value(department.code, final_totals)
    base_decision_count = _count_value(department.code, base_totals)
    support_amount = int(final_totals.get("support_amount") or 0)
    base_support_amount = int(base_totals.get("support_amount") or 0)
    approach_count = int(final_totals.get("approach_count") or 0)
    communication_count = int(final_totals.get("communication_count") or 0)
    base_approach_count = int(base_totals.get("approach_count") or 0)
    base_communication_count = int(base_totals.get("communication_count") or 0)
    active_days = (
        MemberDailyMetricEntry.objects.filter(
            department=department,
            entry_date__range=(scope.start_date, scope.end_date),
        )
        .values("entry_date")
        .distinct()
        .count()
    )
    daily_rows = _daily_report_rows(department=department, scope=scope)
    highest_amount_day = max(daily_rows, key=lambda row: row["amount_value"], default=None)
    lowest_amount_day = min(daily_rows, key=lambda row: row["amount_value"], default=None)

    return {
        "department": department,
        "scope": scope,
        "summary_cards": [
            {
                "label": "合計支援金額",
                "value": _format_number(support_amount, "円"),
                "helper": f"即決 {_format_number(base_support_amount, '円')} / 補正 {_format_number(support_amount - base_support_amount, '円')}",
            },
            {"label": "合計件数", "value": _format_number(decision_count), "helper": _wv_count_breakdown_text(final_totals) if department.code == "WV" else ""},
            {"label": "AP / CM数", "value": f"{approach_count:,} / {communication_count:,}", "helper": ""},
            {"label": "稼働日数", "value": _format_number(active_days), "helper": ""},
            {"label": "コミュ率", "value": _format_percentage(_percentage(base_communication_count, base_approach_count)), "helper": "通常実績ベース"},
            {"label": "決済率", "value": _format_percentage(_percentage(base_decision_count, base_communication_count)), "helper": "通常実績ベース"},
            {"label": "1決済当たりの平均", "value": _format_number(_safe_average(support_amount, decision_count), "円"), "helper": ""},
            {
                "label": "1稼働当たりの平均",
                "value": _format_number(_safe_average(support_amount, active_days), "円"),
                "helper": f"件数 {_format_number(_safe_average(decision_count, active_days))}",
            },
            {
                "label": "最高金額達成日",
                "value": highest_amount_day["amount_text"] if highest_amount_day else "-",
                "helper": highest_amount_day["date_text"] if highest_amount_day else "",
            },
            {
                "label": "最低金額達成日",
                "value": lowest_amount_day["amount_text"] if lowest_amount_day else "-",
                "helper": lowest_amount_day["date_text"] if lowest_amount_day else "",
            },
        ],
        "target_cards": [
            {"label": "目標金額", "value": _format_number(target_amount, "円")},
            {"label": "補正込み実績", "value": _format_number(support_amount, "円")},
            {"label": "目標差分", "value": _format_diff(support_amount - target_amount, unit="円")},
            {"label": "達成率", "value": _format_percentage(_percentage(support_amount, target_amount))},
        ],
        "adjustment_cards": [
            {"label": "補正金額", "value": _format_number(support_amount - base_support_amount, "円")},
            {"label": "補正件数", "value": _format_number(decision_count - base_decision_count)},
            {"label": "戻り件数", "value": _format_number(_return_count_value(final_totals))},
            {"label": "戻り金額", "value": _format_number(_return_amount_value(final_totals), "円")},
        ],
        "daily_rows": daily_rows,
        "member_rows": _member_report_rows(department=department, scope=scope),
    }
