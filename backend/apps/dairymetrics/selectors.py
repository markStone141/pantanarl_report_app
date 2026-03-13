from calendar import monthrange
from datetime import date, timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.targets.models import Period

from .models import (
    MemberDailyMetricEntry,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)

ENTRY_METRIC_FIELDS = [
    "approach_count",
    "communication_count",
    "result_count",
    "support_amount",
    "cs_count",
    "refugee_count",
]

ADJUSTMENT_METRIC_FIELDS = [
    "approach_count",
    "communication_count",
    "result_count",
    "support_amount",
    "return_postal_count",
    "return_postal_amount",
    "return_qr_count",
    "return_qr_amount",
    "cs_count",
    "refugee_count",
]

RANKING_METRIC_SPECS = [
    {"key": "count_value", "label": "件数", "icon": "fa-check-to-slot"},
    {"key": "support_amount", "label": "金額", "icon": "fa-yen-sign"},
    {"key": "approach_count", "label": "アプローチ数", "icon": "fa-bullseye"},
    {"key": "communication_rate", "label": "コミュ率", "icon": "fa-wave-square"},
    {"key": "communication_count", "label": "コミュニケーション数", "icon": "fa-comments"},
    {"key": "participation_rate", "label": "参加率", "icon": "fa-user-check"},
    {"key": "average_support_amount", "label": "平均支援額", "icon": "fa-coins"},
]


def _default_department_code_for_member(member, departments):
    department_map = {department.code: department for department in departments}
    if getattr(member, "default_department_id", None) and member.default_department:
        if member.default_department.code in department_map:
            return member.default_department.code
    member_department_code = (
        Department.objects.filter(is_active=True, member_links__member=member)
        .order_by("code")
        .values_list("code", flat=True)
        .first()
    )
    if member_department_code and member_department_code in department_map:
        return member_department_code
    return departments[0].code if departments else ""


def _zero_totals():
    return {field: 0 for field in {*ENTRY_METRIC_FIELDS, *ADJUSTMENT_METRIC_FIELDS}}


def _aggregate_totals(entries, adjustments):
    totals = _zero_totals()
    entry_totals = entries.aggregate(**{field: Sum(field) for field in ENTRY_METRIC_FIELDS})
    adjustment_totals = adjustments.aggregate(**{field: Sum(field) for field in ADJUSTMENT_METRIC_FIELDS})
    for field in ENTRY_METRIC_FIELDS:
        totals[field] = int(entry_totals.get(field) or 0)
    for field in ADJUSTMENT_METRIC_FIELDS:
        totals[field] = int(totals.get(field) or 0) + int(adjustment_totals.get(field) or 0)
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


def _comparison_label_precise(rate, *, digits=2):
    if rate is None:
        return "-"
    sign = "+" if rate > 0 else ""
    return f"{sign}{rate:.{digits}f}%"


def _format_diff_display(metric_key, value, *, digits=2):
    if value is None:
        return "-"
    if metric_key in {"communication_rate", "participation_rate"}:
        return f"{value:.{digits}f}%"
    if metric_key in {"support_amount", "average_support_amount"}:
        return f"{value:,.0f}"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _rate_value(numerator, denominator):
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 1)


def _rate_text(numerator, denominator):
    value = _rate_value(numerator, denominator)
    if value is None:
        return "-"
    return f"{value}%"


def _average_support_amount_value(amount_value, count_value):
    if count_value <= 0:
        return None
    return round(amount_value / count_value, 1)


def _field_cell(*, field, value, entry_date, editable=True, is_empty=None):
    return {
        "field": field,
        "value": value,
        "raw_value": value,
        "entry_date": entry_date,
        "editable": editable,
        "is_empty": (value in {"", "-", None}) if is_empty is None else is_empty,
    }


def _display_amount_value(totals, *, include_returns=False):
    amount_value = int(totals["support_amount"])
    if include_returns:
        amount_value += int(totals["return_postal_amount"]) + int(totals["return_qr_amount"])
    return amount_value


def _count_value_for_department(department, totals, *, include_returns=False):
    if department.code == "WV":
        count_value = int(totals["cs_count"]) + int(totals["refugee_count"])
    else:
        count_value = int(totals["result_count"])
    if include_returns:
        count_value += int(totals["return_postal_count"]) + int(totals["return_qr_count"])
    return count_value


def _summarize_changes(current, previous, department, *, include_returns=False):
    comparisons = []
    labels = {
        "approach_count": "アプローチ",
        "communication_count": "コミュニケーション",
        "result_count": "件数",
        "support_amount": "金額",
    }
    for field, label in labels.items():
        if field == "result_count":
            current_value = _count_value_for_department(department, current, include_returns=include_returns)
            previous_value = _count_value_for_department(department, previous, include_returns=include_returns)
        elif field == "support_amount":
            current_value = _display_amount_value(current, include_returns=include_returns)
            previous_value = _display_amount_value(previous, include_returns=include_returns)
        else:
            current_value = current[field]
            previous_value = previous[field]
        delta = current_value - previous_value
        rate = _change_rate(current_value, previous_value)
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


def _department_totals(member, department, start_date, end_date, *, include_adjustments=True):
    entries = MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date__range=(start_date, end_date))
    adjustments = MetricAdjustment.objects.none()
    if include_adjustments:
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


def _count_label_for_department(department):
    return "CS/難民" if department.code == "WV" else "件数"


def _count_breakdown_text(department, totals, *, include_returns=False):
    if department.code != "WV":
        base_text = f"現場 {int(totals['result_count'])}"
    else:
        base_text = f"現場 CS {int(totals['cs_count'])} / 難民 {int(totals['refugee_count'])}"
    if not include_returns:
        return base_text
    return " / ".join(
        [
            base_text,
            f"郵送 {int(totals['return_postal_count'])}",
            f"QR {int(totals['return_qr_count'])}",
        ]
    )


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


def _build_member_rankings(department, members, start_date, end_date, *, include_returns=False, include_adjustments=True):
    rankings = []
    for ranked_member in members:
        totals = _department_totals(
            ranked_member,
            department,
            start_date,
            end_date,
            include_adjustments=include_adjustments,
        )
        active_days = MemberDailyMetricEntry.objects.filter(
            member=ranked_member,
            department=department,
            entry_date__range=(start_date, end_date),
        ).count() or 1
        rankings.append(
            {
                "member_id": ranked_member.id,
                "count_value": _count_value_for_department(department, totals, include_returns=include_returns),
                "amount_value": _display_amount_value(totals, include_returns=include_returns),
                "approach_average": round(int(totals["approach_count"]) / active_days, 1),
            }
        )
    return rankings


def _metric_value_for_today(metric_key, department, totals):
    if metric_key == "approach_count":
        return int(totals["approach_count"])
    if metric_key == "communication_count":
        return int(totals["communication_count"])
    if metric_key == "count_value":
        return _count_value_for_department(department, totals)
    if metric_key == "communication_rate":
        return _rate_value(int(totals["communication_count"]), int(totals["approach_count"]))
    if metric_key == "participation_rate":
        return _rate_value(_count_value_for_department(department, totals), int(totals["communication_count"]))
    if metric_key == "average_support_amount":
        return _average_support_amount_value(int(totals["support_amount"]), _count_value_for_department(department, totals))
    return int(totals["support_amount"])


def _metric_value_for_scope(metric_key, department, totals, *, include_returns=False):
    if metric_key == "approach_count":
        return int(totals["approach_count"])
    if metric_key == "communication_count":
        return int(totals["communication_count"])
    if metric_key == "count_value":
        return _count_value_for_department(department, totals, include_returns=include_returns)
    if metric_key == "communication_rate":
        return _rate_value(int(totals["communication_count"]), int(totals["approach_count"]))
    if metric_key == "participation_rate":
        return _rate_value(
            _count_value_for_department(department, totals),
            int(totals["communication_count"]),
        )
    if metric_key == "average_support_amount":
        return _average_support_amount_value(
            int(totals["support_amount"]),
            _count_value_for_department(department, totals),
        )
    return _display_amount_value(totals, include_returns=include_returns)


def _metric_diff_text(value, average):
    if value is None:
        return "-"
    if average <= 0:
        return "-"
    diff_rate = round(((value - average) / average) * 100, 1)
    sign = "+" if diff_rate > 0 else ""
    return f"{sign}{diff_rate}%"


def _metric_display_text(metric_key, department, totals, *, include_returns=False):
    value = _metric_value_for_scope(metric_key, department, totals, include_returns=include_returns)
    return _format_metric_display(metric_key, value)


def _format_metric_display(metric_key, value):
    if value is None:
        return "-"
    if metric_key in {"communication_rate", "participation_rate"}:
        return f"{value}%"
    if metric_key in {"support_amount", "average_support_amount"}:
        return f"{value:,}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _metric_previous_comparison(metric_key, department, current_totals, previous_totals, *, include_returns=False):
    current_value = _metric_value_for_scope(metric_key, department, current_totals, include_returns=include_returns)
    previous_value = _metric_value_for_scope(metric_key, department, previous_totals, include_returns=include_returns)
    if current_value is None or previous_value is None:
        return "-"
    rate_text = _comparison_label(_change_rate(current_value, previous_value))
    if metric_key in {"communication_rate", "participation_rate"}:
        delta_value = round(current_value - previous_value, 1)
        sign = "+" if delta_value > 0 else ""
        delta_text = f"{sign}{delta_value}pt"
    else:
        delta_value = round(current_value - previous_value, 1)
        if metric_key in {"support_amount", "average_support_amount"}:
            delta_text = _format_metric_display(metric_key, delta_value)
            if delta_value > 0:
                delta_text = f"+{delta_text}"
        else:
            if isinstance(delta_value, float) and delta_value.is_integer():
                delta_value = int(delta_value)
            sign = "+" if delta_value > 0 else ""
            delta_text = f"{sign}{delta_value}"
    return f"{delta_text} / {rate_text}"


def _members_with_scope_activity(department, start_date, end_date, *, today_only=False):
    if today_only:
        member_ids = set(
            MemberDailyMetricEntry.objects.filter(
                department=department,
                entry_date=start_date,
            ).values_list("member_id", flat=True)
        )
    else:
        member_ids = set(
            MemberDailyMetricEntry.objects.filter(
                department=department,
                entry_date__range=(start_date, end_date),
            ).values_list("member_id", flat=True)
        )
        member_ids.update(
            MetricAdjustment.objects.filter(
                department=department,
                target_date__range=(start_date, end_date),
            ).values_list("member_id", flat=True)
        )
    return list(Member.objects.active().filter(id__in=member_ids).order_by("name"))


def _build_scope_ranking_metrics(member, department, start_date, end_date, *, today_only=False):
    members = _members_with_scope_activity(department, start_date, end_date, today_only=today_only)
    if not members:
        return []
    include_returns = not today_only
    include_adjustments = not today_only
    member_totals = {
        current_member.id: _department_totals(
            current_member,
            department,
            start_date,
            end_date,
            include_adjustments=include_adjustments,
        )
        for current_member in members
    }
    metrics = []
    for spec in RANKING_METRIC_SPECS:
        ranked_rows = []
        for current_member in members:
            totals = member_totals[current_member.id]
            ranked_rows.append(
                {
                    "member_id": current_member.id,
                    "member_name": current_member.name,
                    "value": _metric_value_for_scope(spec["key"], department, totals, include_returns=include_returns),
                    "value_text": _metric_display_text(spec["key"], department, totals, include_returns=include_returns),
                }
            )
        ranked_rows.sort(key=lambda row: (-(row["value"] if row["value"] is not None else -1), row["member_name"]))
        top_rows = [
            {
                **row,
                "rank": index,
            }
            for index, row in enumerate(ranked_rows[:3], start=1)
        ]
        self_row = next((row for index, row in enumerate(ranked_rows, start=1) if row["member_id"] == member.id), None)
        self_rank = next((index for index, row in enumerate(ranked_rows, start=1) if row["member_id"] == member.id), None)
        metrics.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "icon": spec["icon"],
                "leaders": top_rows,
                "rows": [
                    {
                        **row,
                        "rank": index,
                        "is_self": row["member_id"] == member.id,
                    }
                    for index, row in enumerate(ranked_rows, start=1)
                ],
                "self_row": None if self_rank and self_rank <= 3 else {
                    "rank": self_rank,
                    "member_name": self_row["member_name"] if self_row else member.name,
                    "value": self_row["value"] if self_row else 0,
                    "value_text": self_row["value_text"] if self_row else "-",
                },
            }
        )
    return metrics


def _build_admin_daily_ranking_metrics(department, today):
    members = _members_with_scope_activity(department, today, today, today_only=True)
    if not members:
        return []
    member_totals = {
        current_member.id: _department_totals(
            current_member,
            department,
            today,
            today,
            include_adjustments=False,
        )
        for current_member in members
    }
    metrics = []
    for spec in RANKING_METRIC_SPECS:
        ranked_rows = []
        for current_member in members:
            totals = member_totals[current_member.id]
            ranked_rows.append(
                {
                    "member_id": current_member.id,
                    "member_name": current_member.name,
                    "value": _metric_value_for_scope(spec["key"], department, totals, include_returns=False),
                    "value_text": _metric_display_text(spec["key"], department, totals, include_returns=False),
                }
            )
        ranked_rows.sort(key=lambda row: (-(row["value"] if row["value"] is not None else -1), row["member_name"]))
        metrics.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "icon": spec["icon"],
                "rows": [
                    {
                        **row,
                        "rank": index,
                    }
                    for index, row in enumerate(ranked_rows, start=1)
                ],
            }
        )
    return metrics


def _build_scope_average_metrics(member, department, start_date, end_date, *, today_only=False, previous_totals=None, previous_label=None):
    members = _members_with_scope_activity(department, start_date, end_date, today_only=today_only)
    if not members:
        return []
    include_returns = not today_only
    include_adjustments = not today_only
    member_totals = {
        current_member.id: _department_totals(
            current_member,
            department,
            start_date,
            end_date,
            include_adjustments=include_adjustments,
        )
        for current_member in members
    }
    metric_specs = [
        {"key": "approach_count", "label": "アプローチ数", "icon": "fa-bullseye"},
        {"key": "communication_rate", "label": "コミュ率", "icon": "fa-wave-square"},
        {"key": "communication_count", "label": "コミュニケーション数", "icon": "fa-comments"},
        {"key": "participation_rate", "label": "参加率", "icon": "fa-user-check"},
        {"key": "count_value", "label": "件数", "icon": "fa-check-to-slot"},
        {"key": "support_amount", "label": "金額", "icon": "fa-yen-sign"},
        {"key": "average_support_amount", "label": "平均支援額", "icon": "fa-coins"},
    ]
    metrics = []
    for spec in metric_specs:
        values = [
            _metric_value_for_scope(spec["key"], department, member_totals[current_member.id], include_returns=include_returns)
            for current_member in members
        ]
        metric_values = [value for value in values if value is not None]
        average = round(sum(metric_values) / len(metric_values), 1) if metric_values else 0
        self_value = _metric_value_for_scope(
            spec["key"],
            department,
            member_totals.get(member.id, _zero_totals()),
            include_returns=include_returns,
        )
        metrics.append(
            {
                "label": spec["label"],
                "icon": spec["icon"],
                "average_value": average,
                "self_value": self_value,
                "average_text": _format_metric_display(spec["key"], average) if metric_values else "-",
                "self_text": _format_metric_display(spec["key"], self_value),
                "diff_text": _metric_diff_text(self_value, average),
                "previous_label": previous_label,
                "previous_text": (
                    _metric_previous_comparison(
                        spec["key"],
                        department,
                        member_totals.get(member.id, _zero_totals()),
                        previous_totals,
                        include_returns=include_returns,
                    )
                    if previous_totals is not None and previous_label
                    else None
                ),
            }
        )
    return metrics


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
    trend = []
    for offset in range(7):
        current_day = start_date + timedelta(days=offset)
        totals = _zero_totals()
        if current_day in entry_map:
            for field in ENTRY_METRIC_FIELDS:
                totals[field] += int(entry_map[current_day].get(field) or 0)
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
                "count_value": _count_value_for_department(department, totals, include_returns=True),
                "amount_value": _display_amount_value(totals, include_returns=True),
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
                "count_value": _count_value_for_department(department, totals, include_returns=True),
                "amount_value": _display_amount_value(totals, include_returns=True),
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


def _build_best_records(member, department, start_date, end_date, *, include_returns=False, include_adjustments=True):
    best_count_day = None
    best_amount_day = None
    for offset in range((end_date - start_date).days + 1):
        current_day = start_date + timedelta(days=offset)
        totals = _department_totals(
            member,
            department,
            current_day,
            current_day,
            include_adjustments=include_adjustments,
        )
        count_value = _count_value_for_department(department, totals, include_returns=include_returns)
        amount_value = _display_amount_value(totals, include_returns=include_returns)
        if count_value <= 0 and amount_value <= 0:
            continue
        candidate = {
            "date": current_day,
            "count_value": count_value,
            "amount_value": amount_value,
            "count_text": _count_breakdown_text(department, totals, include_returns=include_returns),
        }
        if not best_count_day or candidate["count_value"] > best_count_day["count_value"] or (
            candidate["count_value"] == best_count_day["count_value"] and candidate["amount_value"] > best_count_day["amount_value"]
        ):
            best_count_day = candidate
        if not best_amount_day or candidate["amount_value"] > best_amount_day["amount_value"] or (
            candidate["amount_value"] == best_amount_day["amount_value"] and candidate["count_value"] > best_amount_day["count_value"]
        ):
            best_amount_day = candidate
    return {
        "count": best_count_day,
        "amount": best_amount_day,
    }


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
    include_returns = scope_data["scope"] != "today"
    include_adjustments = scope_data["scope"] != "today"
    previous_start, previous_end = _previous_range(start_date, end_date)
    department_members = list(
        Member.objects.active().filter(department_links__department=department).distinct().order_by("name")
    )
    today_entry = MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date=today).first()
    scope_totals = _department_totals(member, department, start_date, end_date, include_adjustments=include_adjustments)
    previous_totals = _department_totals(
        member,
        department,
        previous_start,
        previous_end,
        include_adjustments=include_adjustments,
    )
    active_days = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date__range=(start_date, end_date),
    ).count() or 1
    changes = _summarize_changes(scope_totals, previous_totals, department, include_returns=include_returns)
    count_value = _count_value_for_department(department, scope_totals, include_returns=include_returns)
    amount_value = _display_amount_value(scope_totals, include_returns=include_returns)
    target_totals = _scope_target_totals(member, department, scope_data)
    goal_count_value = count_value
    goal_amount_value = amount_value
    goal_completed = (
        target_totals["count"] > 0
        and target_totals["amount"] > 0
        and goal_count_value >= target_totals["count"]
        and goal_amount_value >= target_totals["amount"]
    )
    rankings = _build_member_rankings(
        department,
        department_members,
        start_date,
        end_date,
        include_returns=include_returns,
        include_adjustments=include_adjustments,
    )
    count_rank, member_count = _resolve_rank(member.id, rankings, "count_value")
    amount_rank, _ = _resolve_rank(member.id, rankings, "amount_value")
    team_average = _team_averages(rankings)
    trend_section = _build_scope_trend(member, department, scope_data=scope_data, end_date=end_date)
    best_records = _build_best_records(
        member,
        department,
        start_date,
        end_date,
        include_returns=include_returns,
        include_adjustments=include_adjustments,
    )
    previous_scope_label = "前路程比" if scope_data["scope"] == "period" else "前月比" if scope_data["scope"] == "month" else None
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
        "count_text": _count_breakdown_text(department, scope_totals, include_returns=include_returns),
        "amount_value": amount_value,
        "target_count": target_totals["count"],
        "target_amount": target_totals["amount"],
        "goal_count_value": goal_count_value,
        "goal_amount_value": goal_amount_value,
        "goal_completed": goal_completed,
        "can_edit_scope_target": scope_data["scope"] in {"period", "month"},
        "count_rate_text": _progress_label(goal_count_value, target_totals["count"]),
        "amount_rate_text": _progress_label(goal_amount_value, target_totals["amount"]),
        "count_remaining": max(target_totals["count"] - goal_count_value, 0),
        "amount_remaining": max(target_totals["amount"] - goal_amount_value, 0),
        "has_target": target_totals["count"] > 0 or target_totals["amount"] > 0,
        "approach_average": round(scope_totals["approach_count"] / active_days, 1),
        "communication_average": round(scope_totals["communication_count"] / active_days, 1),
        "count_average": round(count_value / active_days, 1),
        "amount_average": round(amount_value / active_days, 1),
        "communication_rate_text": _rate_text(scope_totals["communication_count"], scope_totals["approach_count"]),
        "participation_rate_text": _rate_text(
            _count_value_for_department(department, scope_totals),
            scope_totals["communication_count"],
        ),
        "average_support_amount_text": _format_metric_display(
            "average_support_amount",
            _average_support_amount_value(
                int(scope_totals["support_amount"]),
                _count_value_for_department(department, scope_totals),
            ),
        ),
        "count_change_rate": _comparison_label(
            _change_rate(count_value, _count_value_for_department(department, previous_totals, include_returns=include_returns))
        ),
        "amount_change_rate": _comparison_label(
            _change_rate(amount_value, _display_amount_value(previous_totals, include_returns=include_returns))
        ),
        "changes": changes,
        "count_rank_text": f"{count_rank} / {member_count}" if count_rank else "-",
        "amount_rank_text": f"{amount_rank} / {member_count}" if amount_rank else "-",
        "team_count_average": team_average["count_value"],
        "team_amount_average": team_average["amount_value"],
        "count_average_diff_text": _format_signed_diff(round(count_value - team_average["count_value"], 1)),
        "amount_average_diff_text": _format_signed_diff(round(amount_value - team_average["amount_value"], 1)),
        "trend_section": trend_section,
        "ranking_metrics": _build_scope_ranking_metrics(
            member,
            department,
            start_date,
            end_date,
            today_only=scope_data["scope"] == "today",
        ),
        "scope_average_metrics": _build_scope_average_metrics(
            member,
            department,
            start_date,
            end_date,
            today_only=scope_data["scope"] == "today",
            previous_totals=previous_totals if scope_data["scope"] in {"period", "month"} else None,
            previous_label=previous_scope_label,
        ),
        "best_records": best_records,
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
    default_department_code = _default_department_code_for_member(member, departments)
    selected_department = next(
        (department for department in departments if department.code == (department_code or default_department_code)),
        departments[0],
    )
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


def build_member_ranking_detail(member, *, today=None, department_code=None, scope="today", start_date=None, end_date=None, metric_key=""):
    dashboard = build_member_dashboard(
        member,
        today=today,
        department_code=department_code,
        scope=scope,
        start_date=start_date,
        end_date=end_date,
    )
    selected_card = dashboard["selected_card"]
    if not selected_card:
        return None
    metric = next(
        (item for item in selected_card["ranking_metrics"] if item["key"] == metric_key),
        None,
    )
    if not metric:
        return None
    return {
        "selected_card": selected_card,
        "metric": metric,
    }


def build_member_daily_overview(member, *, department_code="", today=None):
    today_value = today or date.today()
    departments = list(
        Department.objects.filter(is_active=True, member_links__member__is_active=True).distinct().order_by("code")
    )
    selected_department = None
    if department_code:
        selected_department = next((department for department in departments if department.code == department_code), None)
    if not selected_department and departments:
        default_department_code = _default_department_code_for_member(member, departments)
        selected_department = next(
            (department for department in departments if department.code == default_department_code),
            None,
        )
    if not selected_department and departments:
        selected_department = departments[0]

    if not selected_department:
        return {
            "today": today_value,
            "departments": [],
            "selected_department": None,
            "submission_summary": {"target_count": 0, "submitted_count": 0},
            "today_department_totals": [],
            "activity_cards": [],
        }

    activity_cards = []
    department_today_totals = _zero_totals()
    active_count = 0
    closed_count = 0

    members = Member.objects.active().filter(department_links__department=selected_department).distinct().order_by("name")
    for department_member in members:
        today_entry = (
            MemberDailyMetricEntry.objects.filter(
                member=department_member,
                department=selected_department,
                entry_date=today_value,
            )
            .order_by("-updated_at")
            .first()
        )
        if not today_entry:
            continue
        card_totals = {
            "result_count": int(today_entry.result_count or 0),
            "cs_count": int(today_entry.cs_count or 0),
            "refugee_count": int(today_entry.refugee_count or 0),
        }
        activity_cards.append(
            {
                "member": department_member,
                "department": selected_department,
                "status_label": "活動終了" if today_entry.activity_closed else "活動中",
                "is_closed": today_entry.activity_closed,
                "updated_at": timezone.localtime(today_entry.updated_at),
                "count_label": _count_label_for_department(selected_department),
                "count_text": _count_breakdown_text(selected_department, card_totals),
                "count_value": _count_value_for_department(selected_department, card_totals),
                "amount_value": int(today_entry.support_amount or 0),
                "approach_count": int(today_entry.approach_count or 0),
                "communication_count": int(today_entry.communication_count or 0),
                "cs_count": int(today_entry.cs_count or 0),
                "refugee_count": int(today_entry.refugee_count or 0),
                "location_name": (today_entry.location_name or "").strip(),
            }
        )
        if today_entry.activity_closed:
            closed_count += 1
        else:
            active_count += 1
        for field in ENTRY_METRIC_FIELDS:
            department_today_totals[field] += int(getattr(today_entry, field, 0) or 0)

    activity_cards.sort(key=lambda row: row["updated_at"], reverse=True)
    department_totals = [
        {
            "department": selected_department,
            "count_label": _count_label_for_department(selected_department),
            "count_value": _count_value_for_department(selected_department, department_today_totals),
            "amount_value": _display_amount_value(department_today_totals),
            "approach_count": int(department_today_totals["approach_count"]),
            "communication_count": int(department_today_totals["communication_count"]),
            "cs_count": int(department_today_totals["cs_count"]),
            "refugee_count": int(department_today_totals["refugee_count"]),
        }
    ]

    return {
        "today": today_value,
        "departments": departments,
        "selected_department": selected_department,
        "submission_summary": {"target_count": active_count, "submitted_count": closed_count},
        "today_department_totals": department_totals,
        "activity_cards": activity_cards,
    }


def build_member_month_overview(member, *, target_month, department_code="", today=None):
    today_value = today or date.today()
    departments = list(
        Department.objects.filter(is_active=True, member_links__member=member).distinct().order_by("code")
    )
    month_start = target_month.replace(day=1)
    month_end = target_month.replace(day=monthrange(target_month.year, target_month.month)[1])
    month_days = [
        {
            "date": month_start + timedelta(days=offset),
            "day": month_start.day + offset,
            "weekday_label": "月火水木金土日"[(month_start + timedelta(days=offset)).weekday()],
        }
        for offset in range((month_end - month_start).days + 1)
    ]
    if not departments:
        return {
            "departments": [],
            "selected_department": None,
            "month_days": month_days,
            "field_rows": [],
            "adjustment_rows": [],
        }

    default_department_code = _default_department_code_for_member(member, departments)
    selected_department = next(
        (department for department in departments if department.code == (department_code or default_department_code)),
        departments[0],
    )
    month_entries = list(
        MemberDailyMetricEntry.objects.filter(
            member=member,
            department=selected_department,
            entry_date__range=(month_start, month_end),
        )
    )
    month_adjustments = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=selected_department,
            target_date__range=(month_start, month_end),
        )
    )

    entry_daily_totals_by_date = {}
    adjustment_daily_totals_by_date = {}
    location_names_by_date = {}
    entry_totals = _zero_totals()
    adjustment_totals = _zero_totals()

    for entry in month_entries:
        day_totals = entry_daily_totals_by_date.setdefault(entry.entry_date, _zero_totals())
        for field in ENTRY_METRIC_FIELDS:
            value = int(getattr(entry, field, 0) or 0)
            day_totals[field] += value
            entry_totals[field] += value
        normalized_name = (entry.location_name or "").strip()
        if normalized_name:
            location_names_by_date.setdefault(entry.entry_date, [])
            if normalized_name not in location_names_by_date[entry.entry_date]:
                location_names_by_date[entry.entry_date].append(normalized_name)

    for adjustment in month_adjustments:
        day_totals = adjustment_daily_totals_by_date.setdefault(adjustment.target_date, _zero_totals())
        for field in ADJUSTMENT_METRIC_FIELDS:
            value = int(getattr(adjustment, field, 0) or 0)
            day_totals[field] += value
            adjustment_totals[field] += value

    field_active_day_count = sum(
        1
        for month_day in month_days
        if any(int(entry_daily_totals_by_date.get(month_day["date"], {}).get(field) or 0) > 0 for field in ENTRY_METRIC_FIELDS)
        or bool(location_names_by_date.get(month_day["date"]))
    )
    adjustment_active_day_count = sum(
        1
        for month_day in month_days
        if any(int(adjustment_daily_totals_by_date.get(month_day["date"], {}).get(field) or 0) > 0 for field in ADJUSTMENT_METRIC_FIELDS)
    )

    field_metric_specs = [
        {"label": "AP", "field": "approach_count"},
        {"label": "CM", "field": "communication_count"},
    ]
    if selected_department.code == "WV":
        field_metric_specs.extend(
            [
                {"label": "CS", "field": "cs_count"},
                {"label": "難民", "field": "refugee_count"},
            ]
        )
    else:
        field_metric_specs.append({"label": _count_label_for_department(selected_department), "field": "count_value"})
    field_metric_specs.append({"label": "金額", "field": "support_amount"})

    field_metric_rows = []
    for spec in field_metric_specs:
        field = spec["field"]
        if field == "count_value":
            monthly_total = _count_value_for_department(selected_department, entry_totals, include_returns=False)
            monthly_average = round(monthly_total / field_active_day_count, 1) if field_active_day_count else "-"
            cells = []
            for month_day in month_days:
                count_value = _count_value_for_department(
                    selected_department,
                    entry_daily_totals_by_date.get(month_day["date"], _zero_totals()),
                    include_returns=False,
                )
                cells.append(_field_cell(field=field, value=count_value, entry_date=month_day["date"], editable=False, is_empty=count_value == 0))
        elif field == "support_amount":
            monthly_total = _display_amount_value(entry_totals, include_returns=False)
            monthly_average = round(monthly_total / field_active_day_count, 1) if field_active_day_count else "-"
            cells = []
            for month_day in month_days:
                amount_value = _display_amount_value(entry_daily_totals_by_date.get(month_day["date"], _zero_totals()), include_returns=False)
                cells.append(_field_cell(field=field, value=amount_value, entry_date=month_day["date"], editable=False, is_empty=amount_value == 0))
        else:
            monthly_total = int(entry_totals[field])
            monthly_average = round(int(entry_totals[field]) / field_active_day_count, 1) if field_active_day_count else "-"
            cells = []
            for month_day in month_days:
                cell_value = int(entry_daily_totals_by_date.get(month_day["date"], {}).get(field) or 0)
                cells.append(_field_cell(field=field, value=cell_value, entry_date=month_day["date"], editable=False, is_empty=cell_value == 0))
        field_metric_rows.append(
            {
                "label": spec["label"],
                "field": field,
                "editable": False,
                "monthly_total": monthly_total,
                "monthly_average": monthly_average,
                "cells": cells,
            }
        )

    field_metric_rows.append(
        {
            "label": "現場",
            "field": "location_name",
            "editable": False,
            "monthly_total": "",
            "monthly_average": f"{field_active_day_count}日" if field_active_day_count else "-",
            "cells": [
                _field_cell(
                    field="location_name",
                    value=" / ".join(location_names_by_date.get(month_day["date"], [])) or "-",
                    entry_date=month_day["date"],
                    editable=False,
                    is_empty=not location_names_by_date.get(month_day["date"]),
                )
                for month_day in month_days
            ],
        }
    )

    adjustment_metric_specs = [
        {"label": "郵送件数", "field": "return_postal_count"},
        {"label": "郵送金額", "field": "return_postal_amount"},
        {"label": "QR件数", "field": "return_qr_count"},
        {"label": "QR金額", "field": "return_qr_amount"},
    ]
    adjustment_metric_rows = []
    for spec in adjustment_metric_specs:
        field = spec["field"]
        monthly_total = int(adjustment_totals[field])
        monthly_average = round(int(adjustment_totals[field]) / adjustment_active_day_count, 1) if adjustment_active_day_count else "-"
        cells = [
            _field_cell(
                field=field,
                value=int(adjustment_daily_totals_by_date.get(month_day["date"], {}).get(field) or 0),
                entry_date=month_day["date"],
                editable=False,
                is_empty=int(adjustment_daily_totals_by_date.get(month_day["date"], {}).get(field) or 0) == 0,
            )
            for month_day in month_days
        ]
        adjustment_metric_rows.append(
            {
                "label": spec["label"],
                "field": field,
                "editable": False,
                "monthly_total": monthly_total,
                "monthly_average": monthly_average,
                "cells": cells,
            }
        )

    return {
        "departments": departments,
        "selected_department": selected_department,
        "month_days": month_days,
        "field_rows": [{"department": selected_department, "member": member, "metric_rows": field_metric_rows}],
        "adjustment_rows": [{"department": selected_department, "member": member, "metric_rows": adjustment_metric_rows}],
    }


def build_admin_month_overview(*, target_month, department_code="", today=None):
    today_value = today or date.today()
    departments = list(Department.objects.filter(is_active=True, code__in=["UN", "WV"]).order_by("code"))
    month_start = target_month.replace(day=1)
    month_end = target_month.replace(day=monthrange(target_month.year, target_month.month)[1])
    month_days = [
        {
            "date": month_start + timedelta(days=offset),
            "day": month_start.day + offset,
            "weekday_label": "月火水木金土日"[(month_start + timedelta(days=offset)).weekday()],
        }
        for offset in range((month_end - month_start).days + 1)
    ]
    selected_department = None
    if department_code:
        selected_department = next((department for department in departments if department.code == department_code), None)
    if not selected_department and departments:
        selected_department = departments[0]

    field_rows = []
    adjustment_rows = []
    active_today_members = []
    closed_today_members = []

    for department in departments:
        if selected_department and department.id != selected_department.id:
            continue

        members = Member.objects.active().filter(department_links__department=department).distinct().order_by("name")
        member_ids = list(members.values_list("id", flat=True))
        month_entries = list(
            MemberDailyMetricEntry.objects.filter(
                member_id__in=member_ids,
                department=department,
                entry_date__range=(month_start, month_end),
            ).select_related("member")
        )
        month_adjustments = list(
            MetricAdjustment.objects.filter(
                member_id__in=member_ids,
                department=department,
                target_date__range=(month_start, month_end),
            ).select_related("member")
        )
        entry_daily_totals_by_member = {}
        adjustment_daily_totals_by_member = {}
        location_names_by_member = {}
        entry_monthly_totals_by_member = {member_id: _zero_totals() for member_id in member_ids}
        adjustment_monthly_totals_by_member = {member_id: _zero_totals() for member_id in member_ids}
        today_entries_by_member = {}

        for entry in month_entries:
            key = (entry.member_id, entry.entry_date)
            day_totals = entry_daily_totals_by_member.setdefault(key, _zero_totals())
            for field in ENTRY_METRIC_FIELDS:
                value = int(getattr(entry, field, 0) or 0)
                day_totals[field] += value
                entry_monthly_totals_by_member[entry.member_id][field] += value
            if entry.entry_date == today_value:
                current = today_entries_by_member.get(entry.member_id)
                if current is None or entry.updated_at > current.updated_at:
                    today_entries_by_member[entry.member_id] = entry
            normalized_name = (entry.location_name or "").strip()
            if normalized_name:
                location_names_by_member.setdefault(entry.member_id, {}).setdefault(entry.entry_date, [])
                if normalized_name not in location_names_by_member[entry.member_id][entry.entry_date]:
                    location_names_by_member[entry.member_id][entry.entry_date].append(normalized_name)

        for adjustment in month_adjustments:
            key = (adjustment.member_id, adjustment.target_date)
            day_totals = adjustment_daily_totals_by_member.setdefault(key, _zero_totals())
            for field in ADJUSTMENT_METRIC_FIELDS:
                value = int(getattr(adjustment, field, 0) or 0)
                day_totals[field] += value
                adjustment_monthly_totals_by_member[adjustment.member_id][field] += value

        for member in members:
            today_entry = today_entries_by_member.get(member.id)
            if today_entry:
                if today_entry.activity_closed:
                    closed_today_members.append(member)
                    activity_status = "活動終了"
                else:
                    active_today_members.append(member)
                    activity_status = "活動中"
            else:
                activity_status = "未入力"

            member_locations = location_names_by_member.get(member.id, {})
            entry_totals = entry_monthly_totals_by_member.get(member.id, _zero_totals())
            adjustment_totals = adjustment_monthly_totals_by_member.get(member.id, _zero_totals())

            field_active_day_count = sum(
                1
                for month_day in month_days
                if any(int(entry_daily_totals_by_member.get((member.id, month_day["date"]), {}).get(field) or 0) > 0 for field in ENTRY_METRIC_FIELDS)
                or bool(member_locations.get(month_day["date"]))
            )
            adjustment_active_day_count = sum(
                1
                for month_day in month_days
                if any(
                    int(adjustment_daily_totals_by_member.get((member.id, month_day["date"]), {}).get(field) or 0) > 0
                    for field in ADJUSTMENT_METRIC_FIELDS
                )
            )

            field_metric_specs = [
                {"label": "AP", "field": "approach_count"},
                {"label": "CM", "field": "communication_count"},
            ]
            if department.code == "WV":
                field_metric_specs.extend(
                    [
                        {"label": "CS", "field": "cs_count"},
                        {"label": "難民", "field": "refugee_count"},
                    ]
                )
            else:
                field_metric_specs.append({"label": _count_label_for_department(department), "field": "result_count"})
            field_metric_specs.append({"label": "金額", "field": "support_amount"})

            field_metric_rows = []
            for spec in field_metric_specs:
                field = spec["field"]
                if field == "support_amount":
                    monthly_total = _display_amount_value(entry_totals, include_returns=False)
                    monthly_average = round(monthly_total / field_active_day_count, 1) if field_active_day_count else "-"
                    cells = []
                    for month_day in month_days:
                        amount_value = _display_amount_value(
                            entry_daily_totals_by_member.get((member.id, month_day["date"]), _zero_totals()),
                            include_returns=False,
                        )
                        cells.append(
                            _field_cell(
                                field=field,
                                value=amount_value,
                                entry_date=month_day["date"],
                                is_empty=amount_value == 0,
                            )
                        )
                else:
                    monthly_total = int(entry_totals[field])
                    monthly_average = round(int(entry_totals[field]) / field_active_day_count, 1) if field_active_day_count else "-"
                    cells = []
                    for month_day in month_days:
                        cell_value = int(entry_daily_totals_by_member.get((member.id, month_day["date"]), {}).get(field) or 0)
                        cells.append(
                            _field_cell(
                                field=field,
                                value=cell_value,
                                entry_date=month_day["date"],
                                is_empty=cell_value == 0,
                            )
                        )
                field_metric_rows.append(
                    {
                        "label": spec["label"],
                        "field": field,
                        "editable": True,
                        "monthly_total": monthly_total,
                        "monthly_average": monthly_average,
                        "cells": cells,
                    }
                )
            field_metric_rows.append(
                {
                    "label": "現場",
                    "field": "location_name",
                    "editable": True,
                    "monthly_total": "",
                    "monthly_average": f"{field_active_day_count}日" if field_active_day_count else "-",
                    "cells": [
                        _field_cell(
                            field="location_name",
                            value=" / ".join(member_locations.get(month_day["date"], [])) or "-",
                            entry_date=month_day["date"],
                            is_empty=not member_locations.get(month_day["date"]),
                        )
                        for month_day in month_days
                    ],
                }
            )
            field_rows.append(
                {
                    "department": department,
                    "member": member,
                    "metric_rows": field_metric_rows,
                    "active_day_count": field_active_day_count,
                    "day_count_label": "稼働",
                }
            )

            adjustment_metric_specs = [
                {"label": "郵送件数", "field": "return_postal_count"},
                {"label": "郵送金額", "field": "return_postal_amount"},
                {"label": "QR件数", "field": "return_qr_count"},
                {"label": "QR金額", "field": "return_qr_amount"},
            ]
            adjustment_metric_rows = []
            for spec in adjustment_metric_specs:
                field = spec["field"]
                monthly_total = int(adjustment_totals[field])
                monthly_average = round(int(adjustment_totals[field]) / adjustment_active_day_count, 1) if adjustment_active_day_count else "-"
                cells = [
                    _field_cell(
                        field=field,
                        value=int(adjustment_daily_totals_by_member.get((member.id, month_day["date"]), {}).get(field) or 0),
                        entry_date=month_day["date"],
                        is_empty=int(adjustment_daily_totals_by_member.get((member.id, month_day["date"]), {}).get(field) or 0) == 0,
                    )
                    for month_day in month_days
                ]
                adjustment_metric_rows.append(
                    {
                        "label": spec["label"],
                        "field": field,
                        "editable": True,
                        "monthly_total": monthly_total,
                        "monthly_average": monthly_average,
                        "cells": cells,
                    }
                )
            adjustment_rows.append(
                {
                    "department": department,
                    "member": member,
                    "metric_rows": adjustment_metric_rows,
                    "active_day_count": adjustment_active_day_count,
                    "day_count_label": "戻り",
                }
            )

    return {
        "departments": departments,
        "selected_department": selected_department,
        "month_days": month_days,
        "field_rows": field_rows,
        "adjustment_rows": adjustment_rows,
        "activity_summary": {
            "active_count": len(active_today_members),
            "closed_count": len(closed_today_members),
            "active_members": active_today_members,
            "closed_members": closed_today_members,
        },
    }


def build_admin_month_comparison(*, target_month, compare_month, department_code=""):
    departments = list(Department.objects.filter(is_active=True, code__in=["UN", "WV"]).order_by("code"))
    month_start = target_month.replace(day=1)
    month_end = target_month.replace(day=monthrange(target_month.year, target_month.month)[1])
    compare_month_start = compare_month.replace(day=1)
    compare_month_end = compare_month.replace(day=monthrange(compare_month.year, compare_month.month)[1])

    selected_department = None
    if department_code:
        selected_department = next((department for department in departments if department.code == department_code), None)
    if not selected_department and departments:
        selected_department = departments[0]

    rows = []
    monthly_department_totals = []

    for department in departments:
        if selected_department and department.id != selected_department.id:
            continue

        members = Member.objects.active().filter(department_links__department=department).distinct().order_by("name")
        department_current_totals = _zero_totals()
        department_previous_totals = _zero_totals()

        for member in members:
            current_totals = _department_totals(
                member,
                department,
                month_start,
                month_end,
                include_adjustments=True,
            )
            previous_totals = _department_totals(
                member,
                department,
                compare_month_start,
                compare_month_end,
                include_adjustments=True,
            )
            if not any(int(current_totals.get(field) or 0) for field in current_totals) and not any(
                int(previous_totals.get(field) or 0) for field in previous_totals
            ):
                continue

            for field in department_current_totals:
                department_current_totals[field] += int(current_totals.get(field) or 0)
                department_previous_totals[field] += int(previous_totals.get(field) or 0)

            metric_specs = [
                {"label": "AP", "key": "approach_count", "format": "number"},
                {"label": "CM", "key": "communication_count", "format": "number"},
            ]
            if department.code == "WV":
                metric_specs.extend(
                    [
                        {"label": "CS", "key": "cs_count", "format": "number"},
                        {"label": "難民", "key": "refugee_count", "format": "number"},
                    ]
                )
            else:
                metric_specs.append({"label": "件数", "key": "count_value", "format": "number"})
            metric_specs.extend(
                [
                    {"label": "金額", "key": "support_amount", "format": "amount"},
                    {"label": "コミュ率", "key": "communication_rate", "format": "rate"},
                    {"label": "参加率", "key": "participation_rate", "format": "rate"},
                    {"label": "平均支援額", "key": "average_support_amount", "format": "amount"},
                    {"label": "郵送戻り", "key": "return_postal_count", "format": "number"},
                    {"label": "QR戻り", "key": "return_qr_count", "format": "number"},
                ]
            )

            metric_rows = []
            for spec in metric_specs:
                key = spec["key"]
                display_key = key
                if spec["format"] == "amount":
                    display_key = "support_amount"
                elif spec["format"] == "rate":
                    display_key = "communication_rate"
                if key in {"return_postal_count", "return_qr_count"}:
                    current_value = int(current_totals.get(key) or 0)
                    previous_value = int(previous_totals.get(key) or 0)
                elif key == "support_amount":
                    current_value = _display_amount_value(current_totals, include_returns=True)
                    previous_value = _display_amount_value(previous_totals, include_returns=True)
                else:
                    current_value = _metric_value_for_scope(key, department, current_totals, include_returns=False)
                    previous_value = _metric_value_for_scope(key, department, previous_totals, include_returns=False)
                current_numeric = 0 if current_value is None else current_value
                previous_numeric = 0 if previous_value is None else previous_value
                diff_value = current_numeric - previous_numeric
                rate_text = _comparison_label_precise(_change_rate(current_numeric, previous_numeric), digits=2)
                metric_rows.append(
                    {
                        "label": spec["label"],
                        "previous_value": previous_value,
                        "current_value": current_value,
                        "diff_value": diff_value,
                        "previous_text": _format_metric_display(display_key, previous_value),
                        "current_text": _format_metric_display(display_key, current_value),
                        "diff_text": _format_diff_display(display_key, abs(diff_value), digits=2),
                        "rate_text": rate_text,
                        "is_positive": diff_value > 0,
                        "is_negative": diff_value < 0,
                        "is_rate": spec["format"] == "rate",
                    }
                )

            rows.append(
                {
                    "department": department,
                    "member": member,
                    "metric_rows": metric_rows,
                }
            )

        monthly_department_totals.append(
            {
                "department": department,
                "current_count_text": _count_breakdown_text(department, department_current_totals, include_returns=True),
                "previous_count_text": _count_breakdown_text(department, department_previous_totals, include_returns=True),
                "current_amount_value": _display_amount_value(department_current_totals, include_returns=True),
                "previous_amount_value": _display_amount_value(department_previous_totals, include_returns=True),
            }
        )

    return {
        "departments": departments,
        "selected_department": selected_department,
        "target_month": month_start,
        "compare_month": compare_month_start,
        "rows": rows,
        "monthly_department_totals": monthly_department_totals,
    }


def build_admin_daily_overview(*, department_code="", today=None):
    today_value = today or date.today()
    departments = list(Department.objects.filter(is_active=True, code__in=["UN", "WV"]).order_by("code"))
    selected_department = None
    if department_code:
        selected_department = next((department for department in departments if department.code == department_code), None)
    if not selected_department and departments:
        selected_department = departments[0]

    activity_cards = []
    today_department_totals = []
    active_count = 0
    closed_count = 0

    for department in departments:
        if selected_department and department.id != selected_department.id:
            continue

        department_today_totals = _zero_totals()
        members = Member.objects.active().filter(department_links__department=department).distinct().order_by("name")
        for member in members:
            today_entry = (
                MemberDailyMetricEntry.objects.filter(
                    member=member,
                    department=department,
                    entry_date=today_value,
                )
                .order_by("-updated_at")
                .first()
            )
            if today_entry:
                status_label = "活動終了" if today_entry.activity_closed else "活動中"
                card = {
                    "member": member,
                    "department": department,
                    "status_label": status_label,
                    "is_closed": today_entry.activity_closed,
                    "updated_at": timezone.localtime(today_entry.updated_at),
                    "count_label": _count_label_for_department(department),
                    "count_text": _count_breakdown_text(
                        department,
                        {
                            "result_count": int(today_entry.result_count or 0),
                            "cs_count": int(today_entry.cs_count or 0),
                            "refugee_count": int(today_entry.refugee_count or 0),
                        },
                    ),
                    "count_value": _count_value_for_department(
                        department,
                        {
                            "result_count": int(today_entry.result_count or 0),
                            "cs_count": int(today_entry.cs_count or 0),
                            "refugee_count": int(today_entry.refugee_count or 0),
                        },
                    ),
                    "amount_value": int(today_entry.support_amount or 0),
                    "approach_count": int(today_entry.approach_count or 0),
                    "communication_count": int(today_entry.communication_count or 0),
                    "cs_count": int(today_entry.cs_count or 0),
                    "refugee_count": int(today_entry.refugee_count or 0),
                    "location_name": (today_entry.location_name or "").strip(),
                }
                if today_entry.activity_closed:
                    closed_count += 1
                else:
                    active_count += 1
                activity_cards.append(card)
                for field in ENTRY_METRIC_FIELDS:
                    department_today_totals[field] += int(getattr(today_entry, field, 0) or 0)

        today_department_totals.append(
            {
                "department": department,
                "count_label": _count_label_for_department(department),
                "count_value": _count_value_for_department(department, department_today_totals),
                "count_text": _count_breakdown_text(department, department_today_totals),
                "amount_value": _display_amount_value(department_today_totals),
                "approach_count": int(department_today_totals["approach_count"]),
                "communication_count": int(department_today_totals["communication_count"]),
                "cs_count": int(department_today_totals["cs_count"]),
                "refugee_count": int(department_today_totals["refugee_count"]),
            }
        )

    activity_cards.sort(key=lambda row: row["updated_at"], reverse=True)

    return {
        "today": today_value,
        "departments": departments,
        "selected_department": selected_department,
        "submission_summary": {
            "target_count": active_count,
            "submitted_count": closed_count,
        },
        "today_department_totals": today_department_totals,
        "activity_cards": activity_cards,
        "ranking_metrics": _build_admin_daily_ranking_metrics(selected_department, today_value) if selected_department else [],
    }
