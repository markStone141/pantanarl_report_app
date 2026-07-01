from dataclasses import dataclass
from datetime import date, timedelta

from apps.common.target_periods import current_active_period
from apps.targets.models import Period, TARGET_STATUS_PLANNED

from .progress import month_end


@dataclass(frozen=True)
class CloseoutNotesScope:
    key: str
    label: str
    start_date: date
    end_date: date
    period: Period | None = None


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def resolve_closeout_notes_scope(params, *, today: date) -> CloseoutNotesScope:
    requested_period_id = (params.get("period_id") or "").strip()
    requested_month = (params.get("month") or "").strip()
    requested_scope = (params.get("scope") or "today").strip()

    if requested_period_id.isdigit():
        period = Period.objects.exclude(status=TARGET_STATUS_PLANNED).filter(pk=int(requested_period_id)).first()
        if period is not None:
            return CloseoutNotesScope(
                key="period",
                label=f"{period.name}（{period.start_date:%Y/%m/%d} - {period.end_date:%Y/%m/%d}）",
                start_date=period.start_date,
                end_date=period.end_date,
                period=period,
            )

    if requested_month:
        try:
            month_start = date.fromisoformat(f"{requested_month}-01")
        except ValueError:
            month_start = None
        if month_start is not None:
            return CloseoutNotesScope(
                key="month",
                label=month_start.strftime("%Y年%m月"),
                start_date=month_start,
                end_date=month_end(month_start),
            )

    if requested_scope == "yesterday":
        yesterday = today - timedelta(days=1)
        return CloseoutNotesScope("yesterday", "昨日", yesterday, yesterday)
    if requested_scope == "period":
        period = current_active_period(target_date=today)
        if period is not None:
            return CloseoutNotesScope(
                key="period",
                label=f"現路程: {period.name}",
                start_date=period.start_date,
                end_date=period.end_date,
                period=period,
            )
        return CloseoutNotesScope("period", "現路程なし", today, today)
    if requested_scope == "month":
        month_start = today.replace(day=1)
        return CloseoutNotesScope(
            key="month",
            label=month_start.strftime("%Y年%m月"),
            start_date=month_start,
            end_date=month_end(month_start),
        )
    if requested_scope == "custom":
        date_from = _parse_date(params.get("date_from")) or today
        date_to = _parse_date(params.get("date_to")) or date_from
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return CloseoutNotesScope(
            key="custom",
            label=f"{date_from:%Y/%m/%d} - {date_to:%Y/%m/%d}",
            start_date=date_from,
            end_date=date_to,
        )
    return CloseoutNotesScope("today", "今日", today, today)
