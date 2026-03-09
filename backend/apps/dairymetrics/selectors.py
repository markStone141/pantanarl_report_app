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


def _count_value_for_department(department, totals):
    if department.code == "WV":
        return int(totals["cs_count"]) + int(totals["refugee_count"])
    return int(totals["result_count"])


def _count_label_for_department(department):
    return "CS/難民" if department.code == "WV" else "件数"


def _count_breakdown_text(department, totals):
    if department.code != "WV":
        return str(int(totals["result_count"]))
    return f"CS {int(totals['cs_count'])} / 難民 {int(totals['refugee_count'])}"


def _format_signed_diff(value):
    if value > 0:
        return f"+{value}"
    return str(value)


def _build_member_rankings(department, members, month_start, month_end):
    rankings = []
    for ranked_member in members:
        totals = _department_totals(ranked_member, department, month_start, month_end)
        active_days = MemberDailyMetricEntry.objects.filter(
            member=ranked_member,
            department=department,
            entry_date__range=(month_start, month_end),
        ).count() or 1
        rankings.append(
            {
                "member_id": ranked_member.id,
                "count_value": _count_value_for_department(department, totals),
                "amount_value": int(totals["support_amount"]),
                "approach_average": round(int(totals["approach_count"]) / active_days, 1),
            }
        )
    return rankings


def _resolve_rank(member_id, rankings, key):
    ordered = sorted(rankings, key=lambda item: item[key], reverse=True)
    for index, row in enumerate(ordered, start=1):
        if row["member_id"] == member_id:
            return index, len(ordered)
    return None, len(ordered)


def _team_averages(rankings):
    if not rankings:
        return {"count_value": 0, "amount_value": 0, "approach_average": 0.0}
    size = len(rankings)
    return {
        "count_value": round(sum(item["count_value"] for item in rankings) / size, 1),
        "amount_value": round(sum(item["amount_value"] for item in rankings) / size, 1),
        "approach_average": round(sum(item["approach_average"] for item in rankings) / size, 1),
    }


def _build_daily_trend(member, department, *, end_date):
    start_date = end_date - timedelta(days=6)
    entries = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date__range=(start_date, end_date),
    )
    adjustments = MetricAdjustment.objects.filter(
        member=member,
        department=department,
        target_date__range=(start_date, end_date),
    )
    entry_map = {
        row["entry_date"]: row
        for row in entries.values("entry_date").annotate(
            approach_count=Sum("approach_count"),
            communication_count=Sum("communication_count"),
            result_count=Sum("result_count"),
            support_amount=Sum("support_amount"),
            cs_count=Sum("cs_count"),
            refugee_count=Sum("refugee_count"),
        )
    }
    adjustment_map = {
        row["target_date"]: row
        for row in adjustments.values("target_date").annotate(
            approach_count=Sum("approach_count"),
            communication_count=Sum("communication_count"),
            result_count=Sum("result_count"),
            support_amount=Sum("support_amount"),
            cs_count=Sum("cs_count"),
            refugee_count=Sum("refugee_count"),
        )
    }
    trend = []
    for offset in range(7):
        current_day = start_date + timedelta(days=offset)
        totals = _zero_totals()
        if current_day in entry_map:
            for field in METRIC_FIELDS:
                totals[field] += int(entry_map[current_day].get(field) or 0)
        if current_day in adjustment_map:
            for field in METRIC_FIELDS:
                totals[field] += int(adjustment_map[current_day].get(field) or 0)
        trend.append(
            {
                "label": current_day.strftime("%-m/%-d"),
                "count_value": _count_value_for_department(department, totals),
                "amount_value": int(totals["support_amount"]),
            }
        )
    max_count = max((item["count_value"] for item in trend), default=0) or 1
    max_amount = max((item["amount_value"] for item in trend), default=0) or 1
    for item in trend:
        item["count_height"] = max(14, round((item["count_value"] / max_count) * 100)) if item["count_value"] else 12
        item["amount_height"] = max(14, round((item["amount_value"] / max_amount) * 100)) if item["amount_value"] else 12
    return trend


def _build_best_day(member, department, month_start, month_end):
    best_day = None
    for offset in range((month_end - month_start).days + 1):
        current_day = month_start + timedelta(days=offset)
        totals = _department_totals(member, department, current_day, current_day)
        count_value = _count_value_for_department(department, totals)
        amount_value = int(totals["support_amount"])
        if count_value <= 0 and amount_value <= 0:
            continue
        candidate = {
            "date": current_day,
            "count_value": count_value,
            "amount_value": amount_value,
            "count_text": _count_breakdown_text(department, totals),
        }
        if not best_day or candidate["count_value"] > best_day["count_value"] or (
            candidate["count_value"] == best_day["count_value"] and candidate["amount_value"] > best_day["amount_value"]
        ):
            best_day = candidate
    return best_day


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
    department_members = list(
        Member.objects.active().filter(department_links__department=department).distinct().order_by("name")
    )
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
    count_value = _count_value_for_department(department, month_totals)
    rankings = _build_member_rankings(department, department_members, month_start, month_end)
    count_rank, member_count = _resolve_rank(member.id, rankings, "count_value")
    amount_rank, _ = _resolve_rank(member.id, rankings, "amount_value")
    team_average = _team_averages(rankings)
    daily_trend = _build_daily_trend(member, department, end_date=today)
    best_day = _build_best_day(member, department, month_start, today)
    return {
        "department": department,
        "today_status": "入力済み" if today_entry else "未入力",
        "today_entry": today_entry,
        "month_totals": month_totals,
        "count_label": _count_label_for_department(department),
        "count_value": count_value,
        "count_text": _count_breakdown_text(department, month_totals),
        "approach_average": round(month_totals["approach_count"] / active_days, 1),
        "communication_average": round(month_totals["communication_count"] / active_days, 1),
        "week_count_rate": _comparison_label(_change_rate(_count_value_for_department(department, week_totals), _count_value_for_department(department, prev_week_totals))),
        "month_count_rate": _comparison_label(_change_rate(count_value, _count_value_for_department(department, prev_month_totals))),
        "week_amount_rate": _comparison_label(_change_rate(week_totals["support_amount"], prev_week_totals["support_amount"])),
        "month_amount_rate": _comparison_label(_change_rate(month_totals["support_amount"], prev_month_totals["support_amount"])),
        "changes": changes,
        "count_rank_text": f"{count_rank} / {member_count}" if count_rank else "-",
        "amount_rank_text": f"{amount_rank} / {member_count}" if amount_rank else "-",
        "team_count_average": team_average["count_value"],
        "team_amount_average": team_average["amount_value"],
        "count_average_diff_text": _format_signed_diff(round(count_value - team_average["count_value"], 1)),
        "amount_average_diff_text": _format_signed_diff(round(int(month_totals["support_amount"]) - team_average["amount_value"], 1)),
        "daily_trend": daily_trend,
        "best_day": best_day,
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
