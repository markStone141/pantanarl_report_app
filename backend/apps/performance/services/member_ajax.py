from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from apps.dairymetrics.models import MetricAdjustment
from apps.performance.services.formatters import field_amount_text, field_count_text
from apps.performance.services.member_details import (
    attach_transaction_edit_urls,
    build_entry_adjustment_detail_payload,
    build_member_dashboard_entry_rows,
)
from apps.performance.services.navigation import can_edit_member_performance
from apps.performance.services.scopes import (
    resolve_history_period_from_request,
    resolve_performance_history_scope,
)


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


def _entry_edit_next_url(*, member, department, is_admin, readonly_member_view):
    if readonly_member_view:
        return reverse("performance_member_history_insight", args=[member.id, department.id])
    if is_admin:
        return reverse("performance_member_history_detail", args=[member.id, department.id])
    return reverse("performance_member_history")


def _attach_entry_action_urls(*, entry_rows, next_url):
    for row in entry_rows:
        row["edit_url"] = (
            f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
            f"?{urlencode({'next': next_url})}"
        )
        row["delete_url"] = (
            f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
            f"?{urlencode({'next': next_url})}"
        )
    attach_transaction_edit_urls(entry_rows=entry_rows, next_url=next_url)


def build_member_dashboard_detail_context(
    *,
    member,
    department,
    entry_rows,
    adjustment_rows,
    is_admin=False,
    readonly_member_view=False,
    selected_date=None,
    reset_url="",
):
    if selected_date is not None:
        detail_heading = f"{selected_date:%Y/%m/%d} の実績"
        detail_description = "グラフで選択した1日分の日次実績です。"
        adjustment_heading = f"{selected_date:%Y/%m/%d} の補正実績"
    else:
        recent_start = timezone.localdate() - timedelta(days=29)
        recent_end = timezone.localdate()
        detail_heading = "直近30日の実績"
        detail_description = (
            f"{recent_start:%Y/%m/%d} - {recent_end:%Y/%m/%d} の日次実績です。"
            "それ以前は実績閲覧で確認します。"
        )
        adjustment_heading = "直近30日の補正実績"

    if readonly_member_view:
        history_url = reverse("performance_member_history_insight", args=[member.id, department.id])
    elif is_admin:
        history_url = reverse("performance_member_history_detail", args=[member.id, department.id])
    else:
        history_url = reverse("performance_member_history")

    return {
        "member": member,
        "department": department,
        "recent_entry_rows": entry_rows,
        "recent_adjustment_rows": adjustment_rows,
        "detail_heading": detail_heading,
        "detail_description": detail_description,
        "detail_adjustment_heading": adjustment_heading,
        "detail_reset_url": reset_url,
        "detail_history_url": history_url,
        "show_reset_detail": selected_date is not None,
        "is_admin_view": is_admin,
        "readonly_member_view": readonly_member_view,
    }


def build_member_history_day_detail_context(
    *, member, department, selected_date, is_admin=False, readonly_member_view=False
):
    can_edit = can_edit_member_performance(
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    entry_rows = build_member_dashboard_entry_rows(
        member=member,
        department=department,
        month_start=selected_date,
        month_end=selected_date,
        field_count_text=field_count_text,
        field_amount_text=field_amount_text,
    )
    entry_edit_next_url = _entry_edit_next_url(
        member=member,
        department=department,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    if can_edit:
        _attach_entry_action_urls(entry_rows=entry_rows, next_url=entry_edit_next_url)
    adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date=selected_date,
        ).order_by("-target_date", "-created_at")
    )
    return {
        "member": member,
        "department": department,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "detail_heading": f"{selected_date:%Y/%m/%d} の日次実績",
        "detail_adjustment_heading": f"{selected_date:%Y/%m/%d} の補正実績",
        "detail_description": "グラフで選択した1日分の実績です。",
        "show_reset_detail": True,
        "detail_reset_url": entry_edit_next_url,
        "readonly_member_view": readonly_member_view,
        "can_edit": can_edit,
    }


def build_member_history_list_context(
    *, request, member, department, is_admin=False, readonly_member_view=False
):
    today = timezone.localdate()
    dashboard_scope = request.GET.get("dashboard_scope") or "month"
    if dashboard_scope not in {"month", "period", "range"}:
        dashboard_scope = "month"
    dashboard_month = _parse_selected_month(request.GET.get("dashboard_month"), default=today)
    dashboard_period = resolve_history_period_from_request(
        request,
        today=today,
        scope_value=dashboard_scope,
    )
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
    selected_date = _parse_selected_date(request.GET.get("date"))
    try:
        requested_limit = int(request.GET.get("limit") or 5)
    except (TypeError, ValueError):
        requested_limit = 5
    limit = max(5, min(requested_limit, 30))
    payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
        selected_date=selected_date,
        limit=limit,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=field_count_text,
            field_amount_text=field_amount_text,
            **kwargs,
        ),
    )
    entry_rows = payload["entry_rows"]
    can_edit = can_edit_member_performance(
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    if can_edit:
        _attach_entry_action_urls(entry_rows=entry_rows, next_url=request.get_full_path())
    detail_ajax_url = (
        reverse("performance_member_history_insight_list", args=[member.id, department.id])
        if readonly_member_view
        else reverse("performance_member_history_detail_list", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_history_list")
    )
    detail_reset_url = _entry_edit_next_url(
        member=member,
        department=department,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    return {
        "member": member,
        "department": department,
        "entry_rows": entry_rows,
        "adjustment_rows": payload["adjustment_rows"],
        "detail_heading": f"{scope.label} の日次実績",
        "detail_adjustment_heading": f"{scope.label} の補正実績",
        "detail_description": (
            f"{selected_date:%Y/%m/%d} の実績を表示中"
            if selected_date
            else "対象期間の日次実績と補正実績です。"
        ),
        "show_reset_detail": False,
        "readonly_member_view": readonly_member_view,
        "can_edit": can_edit,
        "detail_limit": limit,
        "detail_limit_step": 5,
        "detail_has_more": payload["has_more"],
        "detail_filter_mode": "input" if scope.scope == "range" else "buttons",
        "detail_filter_dates": payload["filter_dates"],
        "detail_selected_date": selected_date,
        "detail_ajax_url": detail_ajax_url,
        "detail_reset_url": detail_reset_url,
    }


def build_member_recent_detail_context(
    *, request, member, department, is_admin=False, readonly_member_view=False
):
    today = timezone.localdate()
    recent_start = today - timedelta(days=29)
    recent_end = today
    selected_date = _parse_selected_date(request.GET.get("date"))
    try:
        requested_limit = int(request.GET.get("limit") or 5)
    except (TypeError, ValueError):
        requested_limit = 5
    limit = max(5, min(requested_limit, 30))
    payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=recent_start,
        end_date=recent_end,
        selected_date=selected_date,
        limit=limit,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=field_count_text,
            field_amount_text=field_amount_text,
            **kwargs,
        ),
    )
    detail_history_url = _entry_edit_next_url(
        member=member,
        department=department,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    recent_detail_ajax_url = (
        reverse("performance_member_insight_recent_detail", args=[member.id, department.id])
        if readonly_member_view
        else reverse("performance_member_detail_recent_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_dashboard_recent_detail")
    )
    recent_detail_reset_url = (
        reverse("performance_member_insight", args=[member.id, department.id])
        if readonly_member_view
        else reverse("performance_member_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_dashboard")
    )
    can_edit = can_edit_member_performance(
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    entry_rows = payload["entry_rows"]
    if can_edit:
        _attach_entry_action_urls(entry_rows=entry_rows, next_url=recent_detail_reset_url)
    return {
        "member": member,
        "department": department,
        "recent_entry_rows": entry_rows,
        "recent_adjustment_rows": payload["adjustment_rows"],
        "detail_heading": "直近30日の実績",
        "detail_adjustment_heading": "直近30日の補正実績",
        "detail_description": (
            f"{selected_date:%Y/%m/%d} の実績を表示中"
            if selected_date
            else f"{recent_start:%Y/%m/%d} - {recent_end:%Y/%m/%d}"
        ),
        "show_reset_detail": False,
        "detail_history_url": detail_history_url,
        "readonly_member_view": readonly_member_view,
        "recent_detail_start": recent_start,
        "recent_detail_end": recent_end,
        "recent_detail_limit": limit,
        "recent_detail_limit_step": 5,
        "recent_detail_selected_date": selected_date,
        "recent_detail_has_more": payload["has_more"],
        "recent_detail_ajax_url": recent_detail_ajax_url,
        "recent_detail_reset_url": recent_detail_reset_url,
        "can_edit": can_edit,
    }
