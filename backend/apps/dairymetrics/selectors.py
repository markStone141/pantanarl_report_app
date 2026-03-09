from calendar import monthrange
from datetime import date, timedelta

from django.db.models import Sum

from apps.accounts.models import Department, Member

from .models import MemberDailyMetricEntry, MetricAdjustment

METRIC_FIELDS = [
    "approach_count",
    "communication_count",
    "result_count",
    "support_amount",
    "cs_count",
    "refugee_count",
]


def _zero_totals():
    return {field: 0 for field in METRIC_FIELDS}


def _aggregate_totals(entries, adjustments):
    totals = _zero_totals()
    entry_totals = entries.aggregate(**{field: Sum(field) for field in METRIC_FIELDS})
    adjustment_totals = adjustments.aggregate(**{field: Sum(field) for field in METRIC_FIELDS})
    for field in METRIC_FIELDS:
        totals[field] = int(entry_totals.get(field) or 0) + int(adjustment_totals.get(field) or 0)
    return totals


def _change_rate(current_value, previous_value):
    if previous_value <= 0:
        return None if current_value <= 0 else 100.0
    return round(((current_value - previous_value) / previous_value) * 100, 1)


def _comparison_label(rate):
    if rate is None:
        return "-"
    sign = "+" if rate > 0 else ""
    return f"{sign}{rate}%"


def _summarize_changes(current, previous):
    comparisons = []
    labels = {
        "approach_count": "アプローチ",
        "communication_count": "コミュニケーション",
        "result_count": "件数",
        "support_amount": "金額",
    }
    for field, label in labels.items():
        delta = current[field] - previous[field]
        comparisons.append({"field": field, "label": label, "delta": delta, "rate": _change_rate(current[field], previous[field])})
    improved = max(comparisons, key=lambda item: item["delta"])
    declined = min(comparisons, key=lambda item: item["delta"])
    return {
        "items": comparisons,
        "improved": improved if improved["delta"] > 0 else None,
        "declined": declined if declined["delta"] < 0 else None,
    }


def _department_totals(member, department, start_date, end_date):
    entries = MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date__range=(start_date, end_date))
    adjustments = MetricAdjustment.objects.filter(member=member, department=department, target_date__range=(start_date, end_date))
    return _aggregate_totals(entries, adjustments)


def build_member_dashboard_card(member, department, *, today=None):
    today = today or date.today()
    month_start = today.replace(day=1)
    last_day = monthrange(today.year, today.month)[1]
    month_end = today.replace(day=last_day)
    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    same_day = min(today.day, monthrange(prev_month_start.year, prev_month_start.month)[1])
    prev_month_cutoff = prev_month_start.replace(day=same_day)
    seven_days_ago = today - timedelta(days=6)
    previous_week_start = seven_days_ago - timedelta(days=7)
    previous_week_end = seven_days_ago - timedelta(days=1)
    today_entry = MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date=today).first()
    month_totals = _department_totals(member, department, month_start, month_end)
    week_totals = _department_totals(member, department, seven_days_ago, today)
    prev_week_totals = _department_totals(member, department, previous_week_start, previous_week_end)
    prev_month_totals = _department_totals(member, department, prev_month_start, prev_month_cutoff)
    active_days = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date__range=(month_start, today),
    ).count() or 1
    changes = _summarize_changes(week_totals, prev_week_totals)
    return {
        "department": department,
        "today_status": "入力済み" if today_entry else "未入力",
        "today_entry": today_entry,
        "month_totals": month_totals,
        "approach_average": round(month_totals["approach_count"] / active_days, 1),
        "communication_average": round(month_totals["communication_count"] / active_days, 1),
        "week_count_rate": _comparison_label(_change_rate(week_totals["result_count"], prev_week_totals["result_count"])),
        "month_count_rate": _comparison_label(_change_rate(month_totals["result_count"], prev_month_totals["result_count"])),
        "week_amount_rate": _comparison_label(_change_rate(week_totals["support_amount"], prev_week_totals["support_amount"])),
        "month_amount_rate": _comparison_label(_change_rate(month_totals["support_amount"], prev_month_totals["support_amount"])),
        "changes": changes,
    }


def build_member_dashboard(member, *, today=None, department_code=None):
    today = today or date.today()
    departments = list(
        Department.objects.filter(is_active=True, member_links__member=member).distinct().order_by("code")
    )
    if not departments:
        return {
            "departments": [],
            "selected_department": None,
            "selected_card": None,
        }
    selected_department = next((department for department in departments if department.code == department_code), departments[0])
    return {
        "departments": departments,
        "selected_department": selected_department,
        "selected_card": build_member_dashboard_card(member, selected_department, today=today),
    }


def build_admin_month_overview(*, target_month):
    departments = Department.objects.filter(is_active=True, code__in=["UN", "WV"]).order_by("code")
    month_start = target_month.replace(day=1)
    month_end = target_month.replace(day=monthrange(target_month.year, target_month.month)[1])
    rows = []
    for department in departments:
        members = Member.objects.active().filter(department_links__department=department).distinct().order_by("name")
        for member in members:
            totals = _department_totals(member, department, month_start, month_end)
            entry_days = MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date__range=(month_start, month_end)).count() or 1
            rows.append(
                {
                    "department": department,
                    "member": member,
                    "totals": totals,
                    "approach_average": round(totals["approach_count"] / entry_days, 1),
                    "communication_average": round(totals["communication_count"] / entry_days, 1),
                }
            )
    return rows
