from django.db.models import Q, Sum
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_department_final_actual_totals_by_codes,
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
from apps.performance.services.member_cards import (
    build_active_member_cards,
    build_scoped_member_cards,
    members_for_history_scope,
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
    build_overall_activity_trend,
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
        "active_member_cards": build_active_member_cards(
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

    active_members = members_for_history_scope(
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
        "active_member_cards": build_scoped_member_cards(
            members=active_members,
            selected_department=department,
            scope=scope,
        ),
        "month_progress_cards": month_progress_cards,
        "period_progress_cards": period_progress_cards,
    }
