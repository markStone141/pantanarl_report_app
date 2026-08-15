from collections import defaultdict

from django.db.models import Sum

from apps.dairymetrics.models import MemberDailyMetricEntry, MetricAdjustment, WVMetricCancellation


ENTRY_FIELDS = ("approach_count", "communication_count", "result_count", "support_amount", "cs_count", "refugee_count")
ADJUSTMENT_FIELDS = ENTRY_FIELDS
CANCELLATION_FIELDS = ("result_count", "support_amount", "cs_count", "refugee_count")
SORT_FIELDS = {"name", "latest", "activity_days", "member_count", "result_count", "support_amount"}


def _filtered(queryset, *, date_field, start_date, end_date, department_id):
    queryset = queryset.filter(
        activity_site__isnull=False,
        **{f"{date_field}__range": (start_date, end_date)},
    )
    if department_id:
        queryset = queryset.filter(department_id=department_id)
    return queryset


def _add_totals(rows, totals_by_site, fields, multiplier=1):
    for row in rows:
        site_id = row["activity_site_id"]
        totals = totals_by_site[site_id]
        totals["site_id"] = site_id
        totals["site_name"] = row["activity_site__canonical_name"]
        for field in fields:
            totals[field] += multiplier * int(row.get(f"sum_{field}") or 0)


def build_activity_site_comparison(*, start_date, end_date, department_id=None, sort="support_amount", direction="desc"):
    """Build per-site final actuals with a fixed six-query plan (no per-site queries)."""
    totals_by_site = defaultdict(
        lambda: {
            "approach_count": 0,
            "communication_count": 0,
            "result_count": 0,
            "support_amount": 0,
            "cs_count": 0,
            "refugee_count": 0,
        }
    )
    activity_dates = defaultdict(set)
    member_ids = defaultdict(set)
    department_codes = defaultdict(set)

    sources = (
        (MemberDailyMetricEntry.objects.all(), "entry_date", ENTRY_FIELDS, 1),
        (MetricAdjustment.objects.all(), "target_date", ADJUSTMENT_FIELDS, 1),
        (WVMetricCancellation.objects.all(), "target_date", CANCELLATION_FIELDS, -1),
    )
    for queryset, date_field, fields, multiplier in sources:
        filtered = _filtered(
            queryset,
            date_field=date_field,
            start_date=start_date,
            end_date=end_date,
            department_id=department_id,
        )
        annotations = {f"sum_{field}": Sum(field) for field in fields}
        grouped_rows = filtered.values("activity_site_id", "activity_site__canonical_name").annotate(**annotations)
        _add_totals(grouped_rows, totals_by_site, fields, multiplier)

        activity_rows = filtered.values_list(
            "activity_site_id", date_field, "member_id", "department__code"
        ).distinct()
        for site_id, activity_date, member_id, department_code in activity_rows:
            activity_dates[site_id].add(activity_date)
            member_ids[site_id].add(member_id)
            department_codes[site_id].add(department_code)

    rows = []
    for site_id, totals in totals_by_site.items():
        totals.update(
            latest_activity_date=max(activity_dates[site_id]),
            activity_days=len(activity_dates[site_id]),
            member_count=len(member_ids[site_id]),
            department_codes=sorted(department_codes[site_id]),
        )
        rows.append(totals)

    sort = sort if sort in SORT_FIELDS else "support_amount"
    direction = direction if direction in {"asc", "desc"} else "desc"
    sort_key = "site_name" if sort == "name" else ("latest_activity_date" if sort == "latest" else sort)
    rows.sort(key=lambda row: (row[sort_key], row["site_name"], row["site_id"]), reverse=direction == "desc")
    return rows
