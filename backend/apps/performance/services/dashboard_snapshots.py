from datetime import date

from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MetricAdjustment
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_department_final_actual_totals_by_codes,
    collect_member_final_actual_totals_by_ids,
)
from apps.performance.services.formatters import (
    amount_text as _amount_text,
    count_text as _count_text,
    final_amount_text as _final_amount_text,
    final_count_subtext as _final_count_subtext,
    final_count_text as _final_count_text,
    final_count_value as _final_count_value,
    wv_count_detail_text as _wv_count_detail_text,
)
from apps.performance.services.progress import (
    build_progress_card,
    collect_adjustment_amounts_by_codes,
    resolve_month_target_amounts_by_code,
    resolve_period_target_amounts_by_code,
)
from apps.performance.services.scopes import (
    period_display_label as _period_display_label,
    resolve_current_period as _resolve_current_period,
)
from apps.performance.services.trends import (
    EMPTY_ADJUSTMENT_TOTALS,
    build_adjustment_totals_map,
    build_overall_activity_trend,
    entry_final_count_value,
)


def _build_activity_member_rows(entries):
    rows = []
    for entry in entries:
        support_amount = int(entry.support_amount or 0)
        daily_target_amount = int(entry.daily_target_amount or 0)
        rows.append(
            {
                "entry_id": entry.id,
                "member_id": entry.member_id,
                "member_name": entry.member.name,
                "department_code": entry.department.code,
                "department_id": entry.department_id,
                "updated_at": timezone.localtime(entry.updated_at).strftime("%H:%M"),
                "location_name": (entry.location_name or "").strip(),
                "amount_text": f"{support_amount:,}円 / {daily_target_amount:,}円",
                "count_text": (
                    f"CS {int(entry.cs_count or 0)} / 難民 {int(entry.refugee_count or 0)}"
                    if entry.department.code == "WV"
                    else f"{int(entry.result_count or 0)}件"
                ),
                "has_email": bool(entry.member.email),
            }
        )
    return rows

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
        department_member_ids = [member.id for member, current_department in member_department_pairs if current_department.id == department.id]
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
        department_member_ids = [member.id for member, current_department in member_department_pairs if current_department.id == department.id]
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
    for latest_entry in closed_entries:
        latest_totals = adjustment_totals_map.get(
            (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
            EMPTY_ADJUSTMENT_TOTALS,
        )
        latest_final_counts.append(entry_final_count_value(entry=latest_entry, adjustment_totals=latest_totals))

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
    }

def _build_scoped_member_cards(*, members, selected_department, scope):
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

def _totals_count_text_for_dashboard(*, department, totals):
    if department is not None:
        return _final_count_text(department_code=department.code, totals=totals)
    total_count = (
        int(totals.get("result_count") or 0)
        + int(totals.get("return_postal_count") or 0)
        + int(totals.get("return_qr_count") or 0)
        + int(totals.get("cs_count") or 0)
        + int(totals.get("refugee_count") or 0)
    )
    return f"{total_count}件相当"

def _today_target_text_for_dashboard(*, department, count_target, amount_target):
    return f"{int(amount_target or 0):,}円"

def _today_rate_text_for_dashboard(*, actual_count, actual_amount, count_target, amount_target):
    amount_rate = None
    if amount_target and int(amount_target) > 0:
        amount_rate = round((int(actual_amount or 0) / int(amount_target)) * 100, 1)
    if amount_rate is not None:
        return f"{amount_rate}%"
    return "-"

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

def _members_for_history_scope(*, department, start_date, end_date):
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

def _build_active_member_cards(*, members, today, target_month, target_period, selected_department=None):
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

def build_performance_dashboard_snapshot(*, department=None, target_month=None, period=None):
    today = timezone.localdate()
    target_month = target_month or today.replace(day=1)
    period = period or _resolve_current_period(today)
    active_entries = MemberDailyMetricEntry.objects.select_related("member", "department").filter(entry_date=today)
    if department:
        active_entries = active_entries.filter(department=department)
        departments = [department]
    else:
        department_ids = list(active_entries.order_by("department__code").values_list("department_id", flat=True).distinct())
        departments = list(Department.objects.filter(id__in=department_ids).order_by("code"))
    active_entries = list(active_entries.order_by("department__code", "member__name"))
    activity_in_progress = [entry for entry in active_entries if not entry.activity_closed]
    activity_finished = [entry for entry in active_entries if entry.activity_closed]
    today_entry_totals = (
        collect_department_final_actual_totals(
            department,
            today,
            today,
            include_adjustments=False,
        )
        if department is not None
        else collect_department_final_actual_totals_by_codes(
            target_codes=[current_department.code for current_department in departments],
            start_date=today,
            end_date=today,
            include_adjustments=False,
        )
    )
    if department is None:
        merged_today_totals = {
            "result_count": 0,
            "support_amount": 0,
            "return_postal_count": 0,
            "return_postal_amount": 0,
            "return_qr_count": 0,
            "return_qr_amount": 0,
            "cs_count": 0,
            "refugee_count": 0,
            "approach_count": 0,
            "communication_count": 0,
        }
        for department_totals in today_entry_totals.values():
            for key in merged_today_totals:
                merged_today_totals[key] += int(department_totals.get(key) or 0)
        today_entry_totals = merged_today_totals
    summary_queryset = DepartmentDailyMetricSummary.objects.filter(entry_date=today)
    if department is not None:
        summary_queryset = summary_queryset.filter(department=department)
    elif departments:
        summary_queryset = summary_queryset.filter(department__in=departments)
    today_targets = summary_queryset.aggregate(
        total_count=Sum("daily_target_count"),
        total_amount=Sum("daily_target_amount"),
    )
    today_target_count = int(today_targets.get("total_count") or 0)
    today_target_amount = int(today_targets.get("total_amount") or 0)
    today_actual_count = _final_count_value(
        department_code=department.code if department is not None else "",
        totals=today_entry_totals,
    ) if department is not None else (
        int(today_entry_totals.get("result_count") or 0)
        + int(today_entry_totals.get("return_postal_count") or 0)
        + int(today_entry_totals.get("return_qr_count") or 0)
        + int(today_entry_totals.get("cs_count") or 0)
        + int(today_entry_totals.get("refugee_count") or 0)
    )
    today_actual_amount = (
        int(today_entry_totals.get("support_amount") or 0)
        + int(today_entry_totals.get("return_postal_amount") or 0)
        + int(today_entry_totals.get("return_qr_amount") or 0)
    )
    if department:
        active_members = list(
            Member.objects.active()
            .filter(department_links__department=department, department_links__department__is_active=True)
            .select_related("default_department")
            .prefetch_related("department_links__department")
            .distinct()
            .order_by("name", "id")
        )
    else:
        active_members = list(
            Member.objects.active()
            .filter(Q(default_department__is_active=True) | Q(department_links__department__is_active=True))
            .select_related("default_department")
            .prefetch_related("department_links__department")
            .distinct()
            .order_by("name", "id")
        )

    target_codes = [department.code for department in departments]

    month_totals_by_code = collect_department_final_actual_totals_by_codes(
        target_codes=target_codes,
        start_date=target_month,
        end_date=today,
        include_adjustments=True,
    )
    period_totals_by_code = collect_department_final_actual_totals_by_codes(
        target_codes=target_codes,
        start_date=period.start_date if period else today,
        end_date=min(period.end_date, today) if period else today,
        include_adjustments=True,
    ) if target_codes else {}
    month_adjustment_amounts = collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=target_month,
        end_date=today,
    )
    period_adjustment_amounts = collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=period.start_date if period else today,
        end_date=min(period.end_date, today) if period else today,
    ) if target_codes else {}

    month_target_amounts = resolve_month_target_amounts_by_code(departments=departments, target_month=target_month)
    period_target_amounts = resolve_period_target_amounts_by_code(departments=departments, period=period)

    month_progress_cards = []
    period_progress_cards = []
    for current_department in departments:
        month_totals = month_totals_by_code.get(current_department.code, {})
        period_totals = period_totals_by_code.get(current_department.code, {})
        month_progress_cards.append(
            build_progress_card(
                label=current_department.code,
                actual_amount=int(month_totals.get("support_amount") or 0)
                + int(month_totals.get("return_postal_amount") or 0)
                + int(month_totals.get("return_qr_amount") or 0),
                target_amount=int(month_target_amounts.get(current_department.code) or 0),
                summary_text=f"{target_month:%Y/%m} の補正込み累計",
                base_actual_amount=max(
                    (
                        int(month_totals.get("support_amount") or 0)
                        + int(month_totals.get("return_postal_amount") or 0)
                        + int(month_totals.get("return_qr_amount") or 0)
                    )
                    - int(month_adjustment_amounts.get(current_department.code) or 0),
                    0,
                ),
                adjustment_amount=int(month_adjustment_amounts.get(current_department.code) or 0),
            )
        )
        period_progress_cards.append(
            build_progress_card(
                label=current_department.code,
                actual_amount=int(period_totals.get("support_amount") or 0)
                + int(period_totals.get("return_postal_amount") or 0)
                + int(period_totals.get("return_qr_amount") or 0),
                target_amount=int(period_target_amounts.get(current_department.code) or 0),
                summary_text=_period_display_label(period),
                base_actual_amount=max(
                    (
                        int(period_totals.get("support_amount") or 0)
                        + int(period_totals.get("return_postal_amount") or 0)
                        + int(period_totals.get("return_qr_amount") or 0)
                    )
                    - int(period_adjustment_amounts.get(current_department.code) or 0),
                    0,
                ),
                adjustment_amount=int(period_adjustment_amounts.get(current_department.code) or 0),
            )
        )

    return {
        "today": today,
        "today_total_count_text": _totals_count_text_for_dashboard(department=department, totals=today_entry_totals),
        "today_total_count_subtext": (
            _final_count_subtext(department_code=department.code, totals=today_entry_totals)
            if department is not None
            else ""
        ),
        "today_total_amount_text": _final_amount_text(totals=today_entry_totals),
        "today_target_text": _today_target_text_for_dashboard(
            department=department,
            count_target=today_target_count,
            amount_target=today_target_amount,
        ),
        "today_rate_text": _today_rate_text_for_dashboard(
            actual_count=today_actual_count,
            actual_amount=today_actual_amount,
            count_target=today_target_count,
            amount_target=today_target_amount,
        ),
        "overall_activity_trend": build_overall_activity_trend(department=department),
        "activity_in_progress": _build_activity_member_rows(activity_in_progress),
        "activity_finished": _build_activity_member_rows(activity_finished),
        "active_member_cards": _build_active_member_cards(
            members=active_members,
            today=today,
            target_month=target_month,
            target_period=period,
            selected_department=department,
        ),
        "month_progress_cards": month_progress_cards,
        "period_progress_cards": period_progress_cards,
        "current_period": period,
        "current_period_display": _period_display_label(period),
    }

def build_performance_history_snapshot(*, department, scope):
    target_codes = [department.code]
    scoped_totals_by_code = collect_department_final_actual_totals_by_codes(
        target_codes=target_codes,
        start_date=scope.start_date,
        end_date=scope.end_date,
        include_adjustments=True,
    )
    scoped_totals = scoped_totals_by_code.get(department.code, {})
    scoped_adjustment_amounts = collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    month_progress_cards = []
    period_progress_cards = []
    if scope.scope == "month" and scope.month_start:
        month_target_amount = int(
            resolve_month_target_amounts_by_code(
                departments=[department],
                target_month=scope.month_start,
            ).get(department.code)
            or 0
        )
        month_progress_cards.append(
            build_progress_card(
                label=department.code,
                actual_amount=int(scoped_totals.get("support_amount") or 0)
                + int(scoped_totals.get("return_postal_amount") or 0)
                + int(scoped_totals.get("return_qr_amount") or 0),
                target_amount=month_target_amount,
                summary_text=f"{scope.month_start:%Y/%m} の補正込み累計",
                base_actual_amount=max(
                    (
                        int(scoped_totals.get("support_amount") or 0)
                        + int(scoped_totals.get("return_postal_amount") or 0)
                        + int(scoped_totals.get("return_qr_amount") or 0)
                    )
                    - int(scoped_adjustment_amounts.get(department.code) or 0),
                    0,
                ),
                adjustment_amount=int(scoped_adjustment_amounts.get(department.code) or 0),
            )
        )
    if scope.scope == "period" and scope.period:
        period_target_amount = int(
            resolve_period_target_amounts_by_code(
                departments=[department],
                period=scope.period,
            ).get(department.code)
            or 0
        )
        period_progress_cards.append(
            build_progress_card(
                label=department.code,
                actual_amount=int(scoped_totals.get("support_amount") or 0)
                + int(scoped_totals.get("return_postal_amount") or 0)
                + int(scoped_totals.get("return_qr_amount") or 0),
                target_amount=period_target_amount,
                summary_text=scope.period.name,
                base_actual_amount=max(
                    (
                        int(scoped_totals.get("support_amount") or 0)
                        + int(scoped_totals.get("return_postal_amount") or 0)
                        + int(scoped_totals.get("return_qr_amount") or 0)
                    )
                    - int(scoped_adjustment_amounts.get(department.code) or 0),
                    0,
                ),
                adjustment_amount=int(scoped_adjustment_amounts.get(department.code) or 0),
            )
        )

    active_members = _members_for_history_scope(
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    return {
        "scope": scope,
        "overall_activity_trend": build_overall_activity_trend(
            department=department,
            start_date=scope.start_date,
            end_date=scope.end_date,
        ),
        "active_member_cards": _build_scoped_member_cards(
            members=active_members,
            selected_department=department,
            scope=scope,
        ),
        "month_progress_cards": month_progress_cards,
        "period_progress_cards": period_progress_cards,
    }
