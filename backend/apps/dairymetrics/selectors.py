from calendar import monthrange
from datetime import date, timedelta

from django.db.models import Sum

from apps.accounts.models import Department, Member
from apps.targets.models import Period

from .models import (
    MemberDailyMetricEntry,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)

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
        rate = _change_rate(current[field], previous[field])
        comparisons.append(
            {
                "field": field,
                "label": label,
                "delta": delta,
                "rate": rate,
                "rate_text": _comparison_label(rate),
            }
        )
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


def _target_totals(member, department, start_date, end_date):
    entry_totals = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date__range=(start_date, end_date),
    ).aggregate(
        daily_target_count=Sum("daily_target_count"),
        daily_target_amount=Sum("daily_target_amount"),
    )
    return {
        "count": int(entry_totals.get("daily_target_count") or 0),
        "amount": int(entry_totals.get("daily_target_amount") or 0),
    }


def _scope_target_totals(member, department, scope_data):
    if scope_data["scope"] == "today":
        return _target_totals(member, department, scope_data["start_date"], scope_data["end_date"])
    if scope_data["scope"] == "period" and scope_data.get("period"):
        target = MemberPeriodMetricTarget.objects.filter(
            member=member,
            department=department,
            period=scope_data["period"],
        ).first()
        return {
            "count": int(target.target_count if target else 0),
            "amount": int(target.target_amount if target else 0),
        }
    if scope_data["scope"] == "month":
        target = MemberMonthMetricTarget.objects.filter(
            member=member,
            department=department,
            target_month=scope_data["start_date"],
        ).first()
        return {
            "count": int(target.target_count if target else 0),
            "amount": int(target.target_amount if target else 0),
        }
    return {"count": 0, "amount": 0}


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


def _progress_rate(actual, target):
    if target <= 0:
        return None
    return round((actual / target) * 100, 1)


def _progress_label(actual, target):
    rate = _progress_rate(actual, target)
    if rate is None:
        return "-"
    return f"{rate}%"


def _previous_range(start_date, end_date):
    span_days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=span_days - 1)
    return previous_start, previous_end


def _member_activity_bounds(member, department, today):
    entry = (
        MemberDailyMetricEntry.objects.filter(member=member, department=department)
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    adjustment = (
        MetricAdjustment.objects.filter(member=member, department=department)
        .order_by("target_date")
        .values_list("target_date", flat=True)
        .first()
    )
    dates = [item for item in [entry, adjustment] if item]
    start_date = min(dates) if dates else today
    return {"start_date": start_date, "end_date": today}


def _resolve_scope(today, scope, *, member=None, department=None, requested_start_date=None, requested_end_date=None):
    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    current_period = (
        Period.objects.filter(start_date__lte=today, end_date__gte=today)
        .order_by("-month", "start_date", "id")
        .first()
    )
    if scope == "period" and current_period:
        return {
            "scope": "period",
            "label": "今路程",
            "summary": current_period.name,
            "start_date": current_period.start_date,
            "end_date": today,
            "period": current_period,
        }
    if scope == "month":
        return {
            "scope": "month",
            "label": "今月",
            "summary": today.strftime("%Y/%m"),
            "start_date": month_start,
            "end_date": today,
            "period": current_period,
        }
    if scope == "custom" and member and department:
        bounds = _member_activity_bounds(member, department, today)
        start_date = requested_start_date or bounds["start_date"]
        end_date = requested_end_date or bounds["end_date"]
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        is_lifetime = requested_start_date is None and requested_end_date is None
        return {
            "scope": "custom",
            "label": "期間指定",
            "summary": "生涯" if is_lifetime else f"{start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}",
            "start_date": start_date,
            "end_date": end_date,
            "period": current_period,
            "custom_start_date": start_date,
            "custom_end_date": end_date,
            "is_lifetime": is_lifetime,
        }
    return {
        "scope": "today",
        "label": "今日",
        "summary": today.strftime("%Y/%m/%d"),
        "start_date": today,
        "end_date": today,
        "period": current_period,
    }


def _build_member_rankings(department, members, start_date, end_date):
    rankings = []
    for ranked_member in members:
        totals = _department_totals(ranked_member, department, start_date, end_date)
        active_days = MemberDailyMetricEntry.objects.filter(
            member=ranked_member,
            department=department,
            entry_date__range=(start_date, end_date),
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


def _normalize_trend_items(trend):
    max_count = max((item["count_value"] for item in trend), default=0) or 1
    max_amount = max((item["amount_value"] for item in trend), default=0) or 1
    for item in trend:
        item["count_height"] = max(14, round((item["count_value"] / max_count) * 100)) if item["count_value"] else 12
        item["amount_height"] = max(14, round((item["amount_value"] / max_amount) * 100)) if item["amount_value"] else 12
    return trend


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
    return _normalize_trend_items(trend)


def _month_start_for(base_date, offset):
    year = base_date.year
    month = base_date.month - offset
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _build_month_trend(member, department, *, end_date, months=6):
    trend = []
    for offset in range(months - 1, -1, -1):
        start_date = _month_start_for(end_date.replace(day=1), offset)
        end_of_month = date(start_date.year, start_date.month, monthrange(start_date.year, start_date.month)[1])
        capped_end_date = min(end_of_month, end_date) if offset == 0 else end_of_month
        totals = _department_totals(member, department, start_date, capped_end_date)
        trend.append(
            {
                "label": start_date.strftime("%y/%-m"),
                "count_value": _count_value_for_department(department, totals),
                "amount_value": int(totals["support_amount"]),
            }
        )
    return _normalize_trend_items(trend)


def _build_period_trend(member, department, *, current_period, limit=4):
    if not current_period:
        return []
    periods = list(
        Period.objects.filter(end_date__lte=current_period.end_date)
        .order_by("-end_date", "-id")[:limit]
    )
    periods.reverse()
    trend = []
    for period in periods:
        totals = _department_totals(member, department, period.start_date, period.end_date)
        trend.append(
            {
                "label": period.name,
                "count_value": _count_value_for_department(department, totals),
                "amount_value": int(totals["support_amount"]),
            }
        )
    return _normalize_trend_items(trend)


def _build_scope_trend(member, department, *, scope_data, end_date):
    if scope_data["scope"] == "today":
        return {
            "title": "過去7日の推移",
            "description": "休憩中でも、その日の動きが見えるように直近7日を表示します。",
            "items": _build_daily_trend(member, department, end_date=end_date),
        }
    if scope_data["scope"] == "period" and scope_data.get("period"):
        return {
            "title": "過去4路程の推移",
            "description": "今の路程と合わせて、直近4路程の流れを並べます。",
            "items": _build_period_trend(member, department, current_period=scope_data["period"], limit=4),
        }
    if scope_data["scope"] == "month":
        return {
            "title": "過去6か月の推移",
            "description": "今月を含む直近6か月の積み上がりを表示します。",
            "items": _build_month_trend(member, department, end_date=end_date, months=6),
        }
    return None


def _build_best_day(member, department, start_date, end_date):
    best_day = None
    for offset in range((end_date - start_date).days + 1):
        current_day = start_date + timedelta(days=offset)
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


def build_member_dashboard_card(
    member,
    department,
    *,
    today=None,
    scope="today",
    start_date=None,
    end_date=None,
    is_lifetime=False,
):
    today = today or date.today()
    scope_data = _resolve_scope(
        today,
        scope,
        member=member,
        department=department,
        requested_start_date=start_date,
        requested_end_date=end_date,
    )
    if scope_data["scope"] == "custom" and is_lifetime:
        scope_data["summary"] = "生涯"
    start_date = scope_data["start_date"]
    end_date = scope_data["end_date"]
    previous_start, previous_end = _previous_range(start_date, end_date)
    department_members = list(
        Member.objects.active().filter(department_links__department=department).distinct().order_by("name")
    )
    today_entry = MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date=today).first()
    scope_totals = _department_totals(member, department, start_date, end_date)
    previous_totals = _department_totals(member, department, previous_start, previous_end)
    active_days = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date__range=(start_date, end_date),
    ).count() or 1
    changes = _summarize_changes(scope_totals, previous_totals)
    count_value = _count_value_for_department(department, scope_totals)
    target_totals = _scope_target_totals(member, department, scope_data)
    goal_completed = (
        target_totals["count"] > 0
        and target_totals["amount"] > 0
        and count_value >= target_totals["count"]
        and int(scope_totals["support_amount"]) >= target_totals["amount"]
    )
    rankings = _build_member_rankings(department, department_members, start_date, end_date)
    count_rank, member_count = _resolve_rank(member.id, rankings, "count_value")
    amount_rank, _ = _resolve_rank(member.id, rankings, "amount_value")
    team_average = _team_averages(rankings)
    trend_section = _build_scope_trend(member, department, scope_data=scope_data, end_date=end_date)
    best_day = _build_best_day(member, department, start_date, end_date)
    return {
        "department": department,
        "scope": scope_data["scope"],
        "scope_label": scope_data["label"],
        "scope_summary": scope_data["summary"],
        "period_obj": scope_data.get("period"),
        "month_start": scope_data["start_date"] if scope_data["scope"] == "month" else None,
        "custom_start_date": scope_data.get("custom_start_date"),
        "custom_end_date": scope_data.get("custom_end_date"),
        "today_status": "入力済み" if today_entry else "未入力",
        "today_entry": today_entry,
        "activity_status": (
            "活動終了" if today_entry and today_entry.activity_closed else "活動中" if today_entry else "未入力"
        ),
        "scope_totals": scope_totals,
        "count_label": _count_label_for_department(department),
        "count_value": count_value,
        "count_text": _count_breakdown_text(department, scope_totals),
        "target_count": target_totals["count"],
        "target_amount": target_totals["amount"],
        "goal_completed": goal_completed,
        "can_edit_scope_target": scope_data["scope"] in {"period", "month"},
        "count_rate_text": _progress_label(count_value, target_totals["count"]),
        "amount_rate_text": _progress_label(int(scope_totals["support_amount"]), target_totals["amount"]),
        "count_remaining": max(target_totals["count"] - count_value, 0),
        "amount_remaining": max(target_totals["amount"] - int(scope_totals["support_amount"]), 0),
        "has_target": target_totals["count"] > 0 or target_totals["amount"] > 0,
        "approach_average": round(scope_totals["approach_count"] / active_days, 1),
        "communication_average": round(scope_totals["communication_count"] / active_days, 1),
        "count_average": round(count_value / active_days, 1),
        "amount_average": round(int(scope_totals["support_amount"]) / active_days, 1),
        "count_change_rate": _comparison_label(
            _change_rate(count_value, _count_value_for_department(department, previous_totals))
        ),
        "amount_change_rate": _comparison_label(
            _change_rate(scope_totals["support_amount"], previous_totals["support_amount"])
        ),
        "changes": changes,
        "count_rank_text": f"{count_rank} / {member_count}" if count_rank else "-",
        "amount_rank_text": f"{amount_rank} / {member_count}" if amount_rank else "-",
        "team_count_average": team_average["count_value"],
        "team_amount_average": team_average["amount_value"],
        "count_average_diff_text": _format_signed_diff(round(count_value - team_average["count_value"], 1)),
        "amount_average_diff_text": _format_signed_diff(round(int(scope_totals["support_amount"]) - team_average["amount_value"], 1)),
        "trend_section": trend_section,
        "best_day": best_day,
        "show_average_metrics": scope_data["scope"] != "today",
        "show_best_day": scope_data["scope"] != "today",
    }


def build_member_dashboard(member, *, today=None, department_code=None, scope="today", start_date=None, end_date=None):
    today = today or date.today()
    departments = list(
        Department.objects.filter(is_active=True, member_links__member=member).distinct().order_by("code")
    )
    if not departments:
        return {
            "departments": [],
            "selected_department": None,
            "selected_card": None,
            "scope_options": [],
            "selected_scope": "today",
        }
    selected_department = next((department for department in departments if department.code == department_code), departments[0])
    scope_data = _resolve_scope(
        today,
        scope,
        member=member,
        department=selected_department,
        requested_start_date=start_date,
        requested_end_date=end_date,
    )
    scope_options = [
        {"value": "today", "label": "今日", "is_active": scope_data["scope"] == "today"},
        {"value": "period", "label": "今路程", "is_active": scope_data["scope"] == "period", "is_disabled": scope_data["period"] is None},
        {"value": "month", "label": "今月", "is_active": scope_data["scope"] == "month"},
        {"value": "custom", "label": "期間指定", "is_active": scope_data["scope"] == "custom"},
    ]
    return {
        "departments": departments,
        "selected_department": selected_department,
        "selected_card": build_member_dashboard_card(
            member,
            selected_department,
            today=today,
            scope=scope_data["scope"],
            start_date=scope_data.get("custom_start_date"),
            end_date=scope_data.get("custom_end_date"),
            is_lifetime=scope_data.get("is_lifetime", False),
        ),
        "scope_options": scope_options,
        "selected_scope": scope_data["scope"],
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
            latest_entry = MemberDailyMetricEntry.objects.filter(
                member=member,
                department=department,
                entry_date__range=(month_start, month_end),
            ).order_by("-entry_date", "-updated_at").first()
            entry_days = MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date__range=(month_start, month_end)).count() or 1
            rows.append(
                {
                    "department": department,
                    "member": member,
                    "totals": totals,
                    "approach_average": round(totals["approach_count"] / entry_days, 1),
                    "communication_average": round(totals["communication_count"] / entry_days, 1),
                    "activity_status": (
                        "活動終了" if latest_entry and latest_entry.activity_closed else "活動中" if latest_entry else "未入力"
                    ),
                }
            )
    return rows
