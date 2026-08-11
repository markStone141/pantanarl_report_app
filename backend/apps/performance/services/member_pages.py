from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from apps.common.target_periods import period_options_active_first
from apps.dairymetrics.forms import MemberScopeTargetForm
from apps.dairymetrics.models import (
    MemberDailyMetricEntry,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_member_final_actual_totals,
)
from apps.performance.services.formatters import (
    field_amount_text,
    field_count_text,
    final_amount_text,
    final_count_subtext,
    final_count_text,
)
from apps.performance.services.member_details import (
    attach_transaction_edit_urls,
    build_entry_adjustment_detail_payload,
    build_member_closeout_note_rows,
    build_member_dashboard_entry_rows,
    build_trend_date_links,
)
from apps.performance.services.navigation import (
    can_edit_member_performance,
    performance_member_page_nav_links,
)
from apps.performance.services.progress import (
    adjustment_totals_dict_from_queryset,
    build_contribution_summary,
    build_progress_card,
    resolve_month_target_amounts_by_code,
    resolve_period_target_amounts_by_code,
    sum_adjustment_amount,
    month_end,
)
from apps.performance.services.scopes import (
    period_display_label,
    period_range_label,
    resolve_current_period,
    resolve_history_period_from_request,
    resolve_performance_history_scope,
)
from apps.performance.services.trends import build_member_activity_trend


def _parse_selected_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_selected_month(value, *, default):
    if not value:
        return default.replace(day=1)
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        return default.replace(day=1)


def build_member_dashboard_context(*, request, member, department, is_admin=False):
    today = timezone.localdate()
    selected_month = _parse_selected_month(request.GET.get("month"), default=today)
    selectedmonth_end = min(month_end(selected_month), today)
    current_period = resolve_current_period(today)
    recent_start = today - timedelta(days=29)
    recent_end = today
    entry_rows = build_member_dashboard_entry_rows(
        member=member,
        department=department,
        month_start=selected_month,
        month_end=selectedmonth_end,
        field_count_text=field_count_text,
        field_amount_text=field_amount_text,
    )
    adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date__range=(selected_month, selectedmonth_end),
        ).order_by("-target_date", "-created_at")
    )
    recent_detail_payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=recent_start,
        end_date=recent_end,
        limit=5,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=field_count_text,
            field_amount_text=field_amount_text,
            **kwargs,
        ),
    )
    activity_trend = build_member_activity_trend(member=member, department=department)
    detail_next_url = (
        reverse("performance_member_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_dashboard")
    )
    attach_transaction_edit_urls(entry_rows=recent_detail_payload["entry_rows"], next_url=detail_next_url)
    for row in recent_detail_payload["entry_rows"]:
        row["edit_url"] = (
            f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
            f"?{urlencode({'next': detail_next_url})}"
        )
        row["delete_url"] = (
            f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
            f"?{urlencode({'next': detail_next_url})}"
        )
    recent_totals = collect_member_final_actual_totals(
        member,
        department,
        recent_start,
        recent_end,
        include_adjustments=True,
    )
    recent_adjustment_queryset = MetricAdjustment.objects.filter(
        member=member,
        department=department,
        target_date__range=(recent_start, recent_end),
    )
    recent_adjustment_totals = adjustment_totals_dict_from_queryset(queryset=recent_adjustment_queryset)
    recent_active_days = (
        MemberDailyMetricEntry.objects.filter(
            member=member,
            department=department,
            entry_date__range=(recent_start, recent_end),
        )
        .values("entry_date")
        .distinct()
        .count()
    )

    member_month_totals = collect_member_final_actual_totals(
        member,
        department,
        selected_month,
        selectedmonth_end,
        include_adjustments=True,
    )
    member_period_totals = collect_member_final_actual_totals(
        member,
        department,
        current_period.start_date if current_period else today,
        min(current_period.end_date, today) if current_period else today,
        include_adjustments=True,
    )
    department_month_totals = collect_department_final_actual_totals(
        department,
        selected_month,
        selectedmonth_end,
        include_adjustments=True,
    )
    department_period_totals = collect_department_final_actual_totals(
        department,
        current_period.start_date if current_period else today,
        min(current_period.end_date, today) if current_period else today,
        include_adjustments=True,
    )
    member_month_target = MemberMonthMetricTarget.objects.filter(
        member=member,
        department=department,
        target_month=selected_month,
    ).first()
    member_period_target = (
        MemberPeriodMetricTarget.objects.filter(
            member=member,
            department=department,
            period=current_period,
        ).first()
        if current_period
        else None
    )
    department_month_target_amount = int(
        resolve_month_target_amounts_by_code(departments=[department], target_month=selected_month).get(department.code) or 0
    )
    department_period_target_amount = int(
        resolve_period_target_amounts_by_code(departments=[department], period=current_period).get(department.code) or 0
    )
    department_month_actual_amount = (
        int(department_month_totals.get("support_amount") or 0)
        + int(department_month_totals.get("return_postal_amount") or 0)
        + int(department_month_totals.get("return_qr_amount") or 0)
    )
    department_period_actual_amount = (
        int(department_period_totals.get("support_amount") or 0)
        + int(department_period_totals.get("return_postal_amount") or 0)
        + int(department_period_totals.get("return_qr_amount") or 0)
    )
    member_month_actual_amount = (
        int(member_month_totals.get("support_amount") or 0)
        + int(member_month_totals.get("return_postal_amount") or 0)
        + int(member_month_totals.get("return_qr_amount") or 0)
    )
    member_period_actual_amount = (
        int(member_period_totals.get("support_amount") or 0)
        + int(member_period_totals.get("return_postal_amount") or 0)
        + int(member_period_totals.get("return_qr_amount") or 0)
    )
    edit_month_target = request.GET.get("edit_month_target") == "1"
    edit_period_target = request.GET.get("edit_period_target") == "1"

    department_month_progress = build_progress_card(
        label="全体の月目標",
        actual_amount=department_month_actual_amount,
        target_amount=department_month_target_amount,
        summary_text=f"{department.code} 全体の{selected_month:%Y/%m}進捗",
        base_actual_amount=int(department_month_totals.get("support_amount") or 0),
        adjustment_amount=(
            int(department_month_totals.get("return_postal_amount") or 0)
            + int(department_month_totals.get("return_qr_amount") or 0)
        ),
    )
    department_month_progress["contribution"] = build_contribution_summary(
        member_actual_amount=member_month_actual_amount,
        department_actual_amount=department_month_actual_amount,
    )
    department_period_progress = build_progress_card(
        label="全体の路程目標",
        actual_amount=department_period_actual_amount,
        target_amount=department_period_target_amount,
        summary_text=f"{department.code} 全体の{period_display_label(current_period)}進捗",
        base_actual_amount=int(department_period_totals.get("support_amount") or 0),
        adjustment_amount=(
            int(department_period_totals.get("return_postal_amount") or 0)
            + int(department_period_totals.get("return_qr_amount") or 0)
        ),
    )
    department_period_progress["contribution"] = build_contribution_summary(
        member_actual_amount=member_period_actual_amount,
        department_actual_amount=department_period_actual_amount,
    )

    return {
        "nav_items": performance_member_page_nav_links(
            member=member,
            department=department,
            is_admin=is_admin,
        ),
        "member": member,
        "department": department,
        "month_label": selected_month.strftime("%Y/%m"),
        "period_label": current_period.name if current_period else "路程未設定",
        "period_range_label": period_range_label(current_period),
        "selected_month": selected_month,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "recent_entry_rows": recent_detail_payload["entry_rows"],
        "recent_adjustment_rows": recent_detail_payload["adjustment_rows"],
        "recent_range_label": f"{recent_start:%Y/%m/%d} - {recent_end:%Y/%m/%d}",
        "recent_detail_start": recent_start,
        "recent_detail_end": recent_end,
        "recent_detail_limit": 5,
        "recent_detail_limit_step": 5,
        "recent_detail_selected_date": None,
        "recent_detail_has_more": recent_detail_payload["has_more"],
        "recent_detail_reset_url": (
            detail_next_url
        ),
        "recent_summary_items": [
            {"key": "approach_total", "label": "合計AP", "value": f"{int(recent_totals.get('approach_count') or 0):,}"},
            {"key": "communication_total", "label": "合計CM", "value": f"{int(recent_totals.get('communication_count') or 0):,}"},
            {
                "key": "count_total",
                "label": "合計件数",
                "value": final_count_text(department_code=department.code, totals=recent_totals),
                "subtext": final_count_subtext(department_code=department.code, totals=recent_totals),
            },
            {"key": "amount_total", "label": "合計金額", "value": final_amount_text(totals=recent_totals)},
            {
                "key": "adjustment_count_total",
                "label": "補正実績件数",
                "value": final_count_text(department_code=department.code, totals=recent_adjustment_totals),
                "subtext": final_count_subtext(department_code=department.code, totals=recent_adjustment_totals),
            },
            {
                "key": "adjustment_amount_total",
                "label": "補正実績金額",
                "value": final_amount_text(totals=recent_adjustment_totals),
            },
            {"key": "active_days", "label": "稼働日数", "value": f"{recent_active_days:,}日"},
        ],
        "activity_trend": activity_trend,
        "trend_date_links": build_trend_date_links(activity_trend),
        "closeout_note_rows": build_member_closeout_note_rows(
            member=member,
            department=department,
            limit=5,
        ),
        "detail_history_url": (
            reverse("performance_member_history_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history")
        ),
        "recent_detail_ajax_url": (
            reverse("performance_member_detail_recent_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_dashboard_recent_detail")
        ),
        "department_month_progress": department_month_progress,
        "department_period_progress": department_period_progress,
        "member_month_progress": build_progress_card(
            label="個人の月目標",
            actual_amount=member_month_actual_amount,
            target_amount=int(member_month_target.target_amount if member_month_target else 0),
            summary_text=f"{member.name} さんの{selected_month:%Y/%m}進捗",
            base_actual_amount=int(member_month_totals.get("support_amount") or 0),
            adjustment_amount=(
                int(member_month_totals.get("return_postal_amount") or 0)
                + int(member_month_totals.get("return_qr_amount") or 0)
            ),
        ),
        "member_period_progress": build_progress_card(
            label="個人の路程目標",
            actual_amount=member_period_actual_amount,
            target_amount=int(member_period_target.target_amount if member_period_target else 0),
            summary_text=f"{member.name} さんの{period_display_label(current_period)}進捗",
            base_actual_amount=int(member_period_totals.get("support_amount") or 0),
            adjustment_amount=(
                int(member_period_totals.get("return_postal_amount") or 0)
                + int(member_period_totals.get("return_qr_amount") or 0)
            ),
        ),
        "month_target_form": MemberScopeTargetForm(
            member=member,
            scope="month",
            department=department,
            target_month=selected_month,
        ),
        "member_month_target": member_month_target,
        "period_target_form": MemberScopeTargetForm(
            member=member,
            scope="period",
            department=department,
            period=current_period,
        ) if current_period else None,
        "member_period_target": member_period_target,
        "edit_month_target": edit_month_target,
        "edit_period_target": edit_period_target,
        "is_admin_view": is_admin,
        "readonly_member_view": False,
        "can_edit": True,
    }

def build_member_history_context(*, request, member, department, is_admin=False):
    today = timezone.localdate()
    dashboard_scope = request.GET.get("dashboard_scope") or "month"
    if dashboard_scope not in {"month", "period", "range"}:
        dashboard_scope = "month"
    dashboard_month = _parse_selected_month(request.GET.get("dashboard_month"), default=today)
    dashboard_period = resolve_history_period_from_request(request, today=today, scope_value=dashboard_scope)
    dashboard_start = request.GET.get("dashboard_start") or ""
    dashboard_end = request.GET.get("dashboard_end") or ""
    scope = resolve_performance_history_scope(
        today=today,
        scope_value=dashboard_scope,
        requested_month=dashboard_month,
        requested_period=dashboard_period,
        requested_start=_parse_selected_date(dashboard_start),
        requested_end=_parse_selected_date(dashboard_end),
    )

    detail_payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
        limit=5,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=field_count_text,
            field_amount_text=field_amount_text,
            **kwargs,
        ),
    )
    entry_rows = detail_payload["entry_rows"]
    entry_edit_next_url = request.get_full_path()
    can_edit = can_edit_member_performance(is_admin=is_admin, readonly_member_view=False)
    if can_edit:
        attach_transaction_edit_urls(entry_rows=entry_rows, next_url=entry_edit_next_url)
        for row in entry_rows:
            row["edit_url"] = (
                f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
                f"?{urlencode({'next': entry_edit_next_url})}"
            )
            row["delete_url"] = (
                f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
                f"?{urlencode({'next': entry_edit_next_url})}"
            )
    adjustment_rows = detail_payload["adjustment_rows"]
    activity_trend = build_member_activity_trend(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    department_scope_totals = collect_department_final_actual_totals(
        department,
        scope.start_date,
        scope.end_date,
        include_adjustments=True,
    )
    member_scope_totals = collect_member_final_actual_totals(
        member,
        department,
        scope.start_date,
        scope.end_date,
        include_adjustments=True,
    )
    department_adjustment_amount = sum_adjustment_amount(
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    member_adjustment_amount = sum_adjustment_amount(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    department_actual_amount = (
        int(department_scope_totals.get("support_amount") or 0)
        + int(department_scope_totals.get("return_postal_amount") or 0)
        + int(department_scope_totals.get("return_qr_amount") or 0)
    )
    member_actual_amount = (
        int(member_scope_totals.get("support_amount") or 0)
        + int(member_scope_totals.get("return_postal_amount") or 0)
        + int(member_scope_totals.get("return_qr_amount") or 0)
    )

    department_progress_cards = []
    member_progress_cards = []
    if scope.scope == "month" and scope.month_start:
        department_target_amount = int(
            resolve_month_target_amounts_by_code(
                departments=[department],
                target_month=scope.month_start,
            ).get(department.code)
            or 0
        )
        member_target = MemberMonthMetricTarget.objects.filter(
            member=member,
            department=department,
            target_month=scope.month_start,
        ).first()
        department_card = build_progress_card(
            label="全体の月目標",
            actual_amount=department_actual_amount,
            target_amount=department_target_amount,
            summary_text=f"{department.code} 全体の{scope.month_start:%Y/%m}進捗",
            base_actual_amount=max(department_actual_amount - department_adjustment_amount, 0),
            adjustment_amount=department_adjustment_amount,
        )
        department_card["contribution"] = build_contribution_summary(
            member_actual_amount=member_actual_amount,
            department_actual_amount=department_actual_amount,
        )
        department_progress_cards.append(department_card)
        member_progress_cards.append(
            build_progress_card(
                label="個人の月目標",
                actual_amount=member_actual_amount,
                target_amount=int(member_target.target_amount if member_target else 0),
                summary_text=f"{member.name} さんの{scope.month_start:%Y/%m}進捗",
                base_actual_amount=max(member_actual_amount - member_adjustment_amount, 0),
                adjustment_amount=member_adjustment_amount,
            )
        )
    elif scope.scope == "period" and scope.period:
        department_target_amount = int(
            resolve_period_target_amounts_by_code(
                departments=[department],
                period=scope.period,
            ).get(department.code)
            or 0
        )
        member_target = MemberPeriodMetricTarget.objects.filter(
            member=member,
            department=department,
            period=scope.period,
        ).first()
        department_card = build_progress_card(
            label="全体の選択路程目標",
            actual_amount=department_actual_amount,
            target_amount=department_target_amount,
            summary_text=f"{department.code} 全体の{scope.period.name}進捗",
            base_actual_amount=max(department_actual_amount - department_adjustment_amount, 0),
            adjustment_amount=department_adjustment_amount,
        )
        department_card["contribution"] = build_contribution_summary(
            member_actual_amount=member_actual_amount,
            department_actual_amount=department_actual_amount,
        )
        department_progress_cards.append(department_card)
        member_progress_cards.append(
            build_progress_card(
                label="個人の選択路程目標",
                actual_amount=member_actual_amount,
                target_amount=int(member_target.target_amount if member_target else 0),
                summary_text=f"{member.name} さんの{scope.period.name}進捗",
                base_actual_amount=max(member_actual_amount - member_adjustment_amount, 0),
                adjustment_amount=member_adjustment_amount,
            )
        )

    return {
        "nav_items": performance_member_page_nav_links(
            member=member,
            department=department,
            is_admin=is_admin,
        ),
        "member": member,
        "department": department,
        "is_admin_view": is_admin,
        "readonly_member_view": False,
        "can_edit": can_edit,
        "dashboard_scope": dashboard_scope,
        "dashboard_month": dashboard_month,
        "dashboard_period": dashboard_period,
        "dashboard_periods": period_options_active_first(target_date=today),
        "dashboard_start": dashboard_start,
        "dashboard_end": dashboard_end,
        "history_scope": scope,
        "activity_trend": activity_trend,
        "trend_date_links": build_trend_date_links(activity_trend),
        "department_progress_cards": department_progress_cards,
        "member_progress_cards": member_progress_cards,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "detail_limit": 5,
        "detail_limit_step": 5,
        "detail_has_more": detail_payload["has_more"],
        "detail_filter_mode": "input" if scope.scope == "range" else "buttons",
        "detail_filter_dates": detail_payload["filter_dates"],
        "detail_selected_date": None,
        "detail_ajax_url": (
            reverse("performance_member_history_detail_list", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history_list")
        ),
        "detail_reset_url": (
            reverse("performance_member_history_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history")
        ),
    }
