from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from apps.common.target_periods import current_active_period
from apps.performance.services.progress import month_end
from apps.targets.models import Period


@dataclass(frozen=True)
class PerformanceHistoryScope:
    scope: str
    label: str
    start_date: date
    end_date: date
    month_start: date | None = None
    period: Period | None = None


def resolve_current_period(today):
    return current_active_period(target_date=today)


def resolve_history_period_from_request(request, *, today, scope_value):
    if scope_value != "period":
        return resolve_current_period(today)
    period_id = request.GET.get("dashboard_period")
    if period_id:
        return Period.objects.filter(pk=period_id).first()
    return resolve_current_period(today)


def period_range_label(period):
    if period is None:
        return ""
    return f"{period.start_date:%Y/%m/%d} - {period.end_date:%Y/%m/%d}"


def period_display_label(period):
    if period is None:
        return "路程未設定"
    return f"{period.name}（{period_range_label(period)}）"


def resolve_performance_history_scope(
    *,
    today,
    scope_value,
    requested_month=None,
    requested_period=None,
    requested_start=None,
    requested_end=None,
):
    if scope_value == "period" and requested_period is not None:
        return PerformanceHistoryScope(
            scope="period",
            label=period_display_label(requested_period),
            start_date=requested_period.start_date,
            end_date=min(requested_period.end_date, today),
            period=requested_period,
        )
    if scope_value == "range":
        start_date = requested_start or (today - timedelta(days=29))
        end_date = requested_end or today
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return PerformanceHistoryScope(
            scope="range",
            label=f"{start_date:%Y/%m/%d} - {end_date:%Y/%m/%d}",
            start_date=start_date,
            end_date=end_date,
        )
    month_start = requested_month or today.replace(day=1)
    return PerformanceHistoryScope(
        scope="month",
        label=month_start.strftime("%Y/%m"),
        start_date=month_start,
        end_date=min(month_end(month_start), today),
        month_start=month_start,
    )
