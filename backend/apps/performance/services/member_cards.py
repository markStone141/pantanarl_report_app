from datetime import date

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.dairymetrics.models import MemberDailyMetricEntry, MetricAdjustment
from apps.dairymetrics.services.final_actuals import collect_member_final_actual_totals_by_ids
from apps.performance.services.formatters import (
    amount_text as _amount_text,
    count_text as _count_text,
    final_amount_text as _final_amount_text,
    final_count_subtext as _final_count_subtext,
    final_count_text as _final_count_text,
    wv_count_detail_text as _wv_count_detail_text,
)
from apps.performance.services.trends import (
    EMPTY_ADJUSTMENT_TOTALS,
    build_adjustment_totals_map,
    entry_final_count_value,
)


def _resolve_member_department_pairs(*, members, selected_department):
    member_department_pairs = []
    for member in members:
        department = resolve_member_card_department(member=member, selected_department=selected_department)
        if department is None:
            continue
        member_department_pairs.append((member, department))
    return member_department_pairs


def _collect_member_totals_by_department(*, member_department_pairs, start_date, end_date):
    totals_by_department = {}
    departments_by_id = {department.id: department for _, department in member_department_pairs}
    for department in departments_by_id.values():
        department_member_ids = [
            member.id
            for member, current_department in member_department_pairs
            if current_department.id == department.id
        ]
        totals_by_department[department.id] = collect_member_final_actual_totals_by_ids(
            member_ids=department_member_ids,
            department=department,
            start_date=start_date,
            end_date=end_date,
            include_adjustments=True,
        )
    return totals_by_department


def _collect_member_latest_entries_by_department(*, member_department_pairs, start_date=None, end_date=None):
    latest_entries_by_department = {}
    adjustment_totals_by_department = {}
    departments_by_id = {department.id: department for _, department in member_department_pairs}
    for department in departments_by_id.values():
        department_member_ids = [
            member.id
            for member, current_department in member_department_pairs
            if current_department.id == department.id
        ]
        entries_qs = MemberDailyMetricEntry.objects.filter(
            member_id__in=department_member_ids,
            department=department,
        )
        if start_date is not None and end_date is not None:
            entries_qs = entries_qs.filter(entry_date__range=(start_date, end_date))
        department_entries = list(
            entries_qs.select_related("member", "department").order_by("member_id", "-entry_date", "-id")
        )
        latest_entries_by_department[department.id] = {}
        picked_entries = []
        for entry in department_entries:
            pair_key = (entry.member_id, entry.department_id)
            bucket = latest_entries_by_department[department.id].setdefault(pair_key, [])
            if len(bucket) < 6:
                bucket.append(entry)
                picked_entries.append(entry)
        adjustment_totals_by_department[department.id] = build_adjustment_totals_map(picked_entries)
    return latest_entries_by_department, adjustment_totals_by_department


def _build_member_recent_metrics(*, entries, adjustment_totals_map, department_code):
    latest_final_counts = []
    closed_entries = [entry for entry in entries if entry.activity_closed][:3]
    recent_activity_items = []
    for latest_entry in closed_entries:
        latest_totals = adjustment_totals_map.get(
            (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
            EMPTY_ADJUSTMENT_TOTALS,
        )
        final_count = entry_final_count_value(entry=latest_entry, adjustment_totals=latest_totals)
        latest_final_counts.append(final_count)
        recent_activity_items.append(
            {
                "date_text": latest_entry.entry_date.strftime("%-m/%-d"),
                "amount_text": _amount_text(latest_entry, latest_totals),
                "count_text": _count_text(latest_entry, latest_totals),
                "count_subtext": (
                    _wv_count_detail_text(
                        cs_count=int(latest_entry.cs_count or 0) + int(latest_totals["cs_count"]),
                        refugee_count=int(latest_entry.refugee_count or 0) + int(latest_totals["refugee_count"]),
                    )
                    if department_code == "WV"
                    else ""
                ),
                "has_result": final_count >= 1,
            }
        )
    recent_activity_items.reverse()

    zero_streak_warning = len(latest_final_counts) == 3 and all(count == 0 for count in latest_final_counts)
    active_streak_good = len(latest_final_counts) == 3 and all(count >= 1 for count in latest_final_counts)
    if not entries:
        return {
            "updated_at": "実績なし",
            "recent_date_text": "-",
            "recent_amount_text": "-",
            "recent_count_text": "-",
            "recent_count_subtext": "",
            "recent_sort_date": None,
            "zero_streak_warning": zero_streak_warning,
            "zero_streak_text": "3稼働連続0件" if zero_streak_warning else "",
            "active_streak_good": active_streak_good,
            "active_streak_text": "3稼働連続1件以上" if active_streak_good else "",
            "recent_activity_items": recent_activity_items,
            "streak_status": "other",
        }

    latest_entry = entries[0]
    latest_totals = adjustment_totals_map.get(
        (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
        EMPTY_ADJUSTMENT_TOTALS,
    )
    return {
        "updated_at": timezone.localtime(latest_entry.updated_at).strftime("%H:%M"),
        "recent_date_text": latest_entry.entry_date.strftime("%Y/%m/%d"),
        "recent_amount_text": _amount_text(latest_entry, latest_totals),
        "recent_count_text": _count_text(latest_entry, latest_totals),
        "recent_count_subtext": (
            _wv_count_detail_text(
                cs_count=int(latest_entry.cs_count or 0) + int(latest_totals["cs_count"]),
                refugee_count=int(latest_entry.refugee_count or 0) + int(latest_totals["refugee_count"]),
            )
            if department_code == "WV"
            else ""
        ),
        "recent_sort_date": latest_entry.entry_date,
        "zero_streak_warning": zero_streak_warning,
        "zero_streak_text": "3稼働連続0件" if zero_streak_warning else "",
        "active_streak_good": active_streak_good,
        "active_streak_text": "3稼働連続1件以上" if active_streak_good else "",
        "recent_activity_items": recent_activity_items,
        "streak_status": "warning" if zero_streak_warning else "positive" if active_streak_good else "other",
    }


def build_scoped_member_cards(*, members, selected_department, scope):
    cards = []
    scope_metric_label = {
        "month": "月累計",
        "period": "路程累計",
        "range": "期間累計",
    }.get(scope.scope, "累計")
    member_department_pairs = _resolve_member_department_pairs(
        members=members,
        selected_department=selected_department,
    )
    department_totals_map = _collect_member_totals_by_department(
        member_department_pairs=member_department_pairs,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    latest_entries_by_pair, adjustment_totals_by_pair = _collect_member_latest_entries_by_department(
        member_department_pairs=member_department_pairs,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    for member, department in member_department_pairs:
        scoped_totals = department_totals_map.get(department.id, {}).get(member.id, {})
        scoped_entries = latest_entries_by_pair.get(department.id, {}).get((member.id, department.id), [])
        latest_adjustment_totals = adjustment_totals_by_pair.get(department.id, {})
        recent_metrics = _build_member_recent_metrics(
            entries=scoped_entries,
            adjustment_totals_map=latest_adjustment_totals,
            department_code=department.code,
        )
        cards.append(
            {
                "member_name": member.name,
                "department_code": department.code,
                "updated_at": recent_metrics["updated_at"],
                "scope_label": scope_metric_label,
                "scope_amount_text": _final_amount_text(totals=scoped_totals),
                "scope_count_text": _final_count_text(department_code=department.code, totals=scoped_totals),
                "scope_count_subtext": _final_count_subtext(department_code=department.code, totals=scoped_totals),
                "recent_date_text": recent_metrics["recent_date_text"],
                "recent_amount_text": recent_metrics["recent_amount_text"],
                "recent_count_text": recent_metrics["recent_count_text"],
                "recent_count_subtext": recent_metrics["recent_count_subtext"],
                "recent_sort_date": recent_metrics["recent_sort_date"],
                "zero_streak_warning": recent_metrics["zero_streak_warning"],
                "zero_streak_text": recent_metrics["zero_streak_text"],
                "active_streak_good": recent_metrics["active_streak_good"],
                "active_streak_text": recent_metrics["active_streak_text"],
                "recent_activity_items": recent_metrics["recent_activity_items"],
                "streak_status": recent_metrics["streak_status"],
                "detail_url": reverse("performance_member_insight", args=[member.id, department.id]),
            }
        )
    cards.sort(
        key=lambda card: (
            card["recent_sort_date"] is not None,
            card["recent_sort_date"] or date.min,
            card["member_name"],
        ),
        reverse=True,
    )
    return cards


def resolve_member_card_department(*, member, selected_department=None):
    if selected_department is not None:
        return selected_department
    if member.default_department_id and member.default_department and member.default_department.is_active:
        return member.default_department
    prefetched_links = getattr(member, "_prefetched_objects_cache", {}).get("department_links")
    if prefetched_links is not None:
        active_departments = sorted(
            [
                link.department
                for link in prefetched_links
                if link.department and link.department.is_active
            ],
            key=lambda department: (department.code, department.id),
        )
        return active_departments[0] if active_departments else None
    return (
        Department.objects.filter(member_links__member=member, is_active=True)
        .order_by("code", "id")
        .first()
    )


def members_for_history_scope(*, department, start_date, end_date):
    active_member_ids = set(
        Member.objects.active()
        .filter(department_links__department=department, department_links__department__is_active=True)
        .values_list("id", flat=True)
    )
    scoped_member_ids = set(
        MemberDailyMetricEntry.objects.filter(
            department=department,
            entry_date__range=(start_date, end_date),
        ).values_list("member_id", flat=True)
    )
    scoped_member_ids.update(
        MetricAdjustment.objects.filter(
            department=department,
            target_date__range=(start_date, end_date),
        ).values_list("member_id", flat=True)
    )
    member_ids = active_member_ids | scoped_member_ids
    if not member_ids:
        return []
    return list(
        Member.objects.filter(
            id__in=member_ids,
            department_links__department=department,
            department_links__department__is_active=True,
        )
        .select_related("default_department")
        .distinct()
        .order_by("name", "id")
    )


def build_active_member_cards(
    *,
    members,
    today,
    target_month,
    target_period,
    selected_department=None,
):
    cards = []
    member_department_pairs = _resolve_member_department_pairs(
        members=members,
        selected_department=selected_department,
    )
    month_totals_map = _collect_member_totals_by_department(
        member_department_pairs=member_department_pairs,
        start_date=target_month,
        end_date=today,
    )
    period_totals_map = _collect_member_totals_by_department(
        member_department_pairs=member_department_pairs,
        start_date=target_period.start_date if target_period else today,
        end_date=min(target_period.end_date, today) if target_period else today,
    )
    latest_entries_by_pair, adjustment_totals_by_pair = _collect_member_latest_entries_by_department(
        member_department_pairs=member_department_pairs,
    )

    for member, department in member_department_pairs:
        month_totals = month_totals_map.get(department.id, {}).get(member.id, {})
        period_totals = period_totals_map.get(department.id, {}).get(member.id, {})
        latest_entries = latest_entries_by_pair.get(department.id, {}).get((member.id, department.id), [])
        latest_adjustment_totals = adjustment_totals_by_pair.get(department.id, {})
        recent_metrics = _build_member_recent_metrics(
            entries=latest_entries,
            adjustment_totals_map=latest_adjustment_totals,
            department_code=department.code,
        )
        cards.append(
            {
                "member_name": member.name,
                "department_code": department.code,
                "updated_at": recent_metrics["updated_at"],
                "month_amount_text": _final_amount_text(totals=month_totals),
                "month_count_text": _final_count_text(department_code=department.code, totals=month_totals),
                "month_count_subtext": _final_count_subtext(department_code=department.code, totals=month_totals),
                "period_amount_text": _final_amount_text(totals=period_totals),
                "period_count_text": _final_count_text(department_code=department.code, totals=period_totals),
                "period_count_subtext": _final_count_subtext(department_code=department.code, totals=period_totals),
                "recent_date_text": recent_metrics["recent_date_text"],
                "recent_amount_text": recent_metrics["recent_amount_text"],
                "recent_count_text": recent_metrics["recent_count_text"],
                "recent_count_subtext": recent_metrics["recent_count_subtext"],
                "recent_sort_date": recent_metrics["recent_sort_date"],
                "zero_streak_warning": recent_metrics["zero_streak_warning"],
                "zero_streak_text": recent_metrics["zero_streak_text"],
                "active_streak_good": recent_metrics["active_streak_good"],
                "active_streak_text": recent_metrics["active_streak_text"],
                "recent_activity_items": recent_metrics["recent_activity_items"],
                "streak_status": recent_metrics["streak_status"],
                "detail_url": reverse("performance_member_insight", args=[member.id, department.id]),
            }
        )
    cards.sort(
        key=lambda card: (
            card["recent_sort_date"] is not None,
            card["recent_sort_date"] or date.min,
            card["member_name"],
        ),
        reverse=True,
    )
    return cards
