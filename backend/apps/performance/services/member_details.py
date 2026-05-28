from django.urls import reverse
from django.utils.http import urlencode

from apps.dairymetrics.models import MemberDailyMetricEntry, MetricAdjustment
from apps.performance.services.trends import build_adjustment_totals_map


def build_member_dashboard_entry_rows(*, member, department, month_start, month_end, field_count_text, field_amount_text):
    member_entries = (
        MemberDailyMetricEntry.objects.select_related("member", "department")
        .prefetch_related("transactions")
        .filter(
            member=member,
            department=department,
        )
    )
    entries = list(member_entries.filter(entry_date__range=(month_start, month_end)).order_by("-entry_date", "-id"))
    build_adjustment_totals_map(entries)
    entry_rows = []
    for entry in entries:
        entry_rows.append(
            {
                "entry": entry,
                "count_text": field_count_text(entry),
                "amount_text": field_amount_text(entry),
                "transactions": list(entry.transactions.all().order_by("created_at", "id")),
            }
        )
    return entry_rows


def attach_transaction_edit_urls(*, entry_rows, next_url):
    for row in entry_rows:
        for transaction in row["transactions"]:
            transaction.edit_url = (
                f"{reverse('performance_transaction_edit', args=[transaction.id])}"
                f"?{urlencode({'next': next_url})}"
            )


def build_detail_filter_dates(*, entry_rows, adjustment_rows):
    unique_dates = set()
    for row in entry_rows:
        unique_dates.add(row["entry"].entry_date)
    for adjustment in adjustment_rows:
        unique_dates.add(adjustment.target_date)
    return [
        {
            "date": current_date.isoformat(),
            "label": current_date.strftime("%m/%d"),
        }
        for current_date in sorted(unique_dates, reverse=True)
    ]


def build_entry_adjustment_detail_payload(
    *,
    member,
    department,
    start_date,
    end_date,
    selected_date=None,
    limit=5,
    entry_rows_builder,
):
    if selected_date is not None:
        entry_rows = entry_rows_builder(
            member=member,
            department=department,
            month_start=selected_date,
            month_end=selected_date,
        )
        adjustment_rows = list(
            MetricAdjustment.objects.filter(
                member=member,
                department=department,
                target_date=selected_date,
            ).order_by("-target_date", "-created_at")
        )
        return {
            "entry_rows": entry_rows,
            "adjustment_rows": adjustment_rows,
            "has_more": False,
            "filter_dates": build_detail_filter_dates(entry_rows=entry_rows, adjustment_rows=adjustment_rows),
        }

    all_entry_rows = entry_rows_builder(
        member=member,
        department=department,
        month_start=start_date,
        month_end=end_date,
    )
    all_adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date__range=(start_date, end_date),
        ).order_by("-target_date", "-created_at")
    )
    sliced_entry_rows = all_entry_rows[:limit]
    sliced_adjustment_rows = all_adjustment_rows[:limit]
    has_more = len(all_entry_rows) > limit or len(all_adjustment_rows) > limit
    return {
        "entry_rows": sliced_entry_rows,
        "adjustment_rows": sliced_adjustment_rows,
        "has_more": has_more,
        "filter_dates": build_detail_filter_dates(entry_rows=all_entry_rows, adjustment_rows=all_adjustment_rows),
    }


def build_trend_date_links(activity_trend):
    dates = list(activity_trend.get("dates") or [])
    labels = list(activity_trend.get("labels") or [])
    visible_count = int(activity_trend.get("default_visible_count") or 0)
    if not dates or not labels or visible_count <= 0:
        return []
    start_index = max(0, len(dates) - visible_count)
    links = []
    for index in range(start_index, len(dates)):
        links.append(
            {
                "date": dates[index],
                "label": labels[index],
            }
        )
    return links
