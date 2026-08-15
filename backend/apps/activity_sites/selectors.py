from collections import defaultdict

from django.db.models import CharField, ExpressionWrapper, F, IntegerField, Sum, Value

from apps.dairymetrics.models import MemberDailyMetricEntry, MetricAdjustment, WVMetricCancellation


ENTRY_FIELDS = ("approach_count", "communication_count", "result_count", "support_amount", "cs_count", "refugee_count")
ADJUSTMENT_FIELDS = ENTRY_FIELDS + (
    "return_postal_count",
    "return_postal_amount",
    "return_qr_count",
    "return_qr_amount",
)
CANCELLATION_FIELDS = ("result_count", "support_amount", "cs_count", "refugee_count")
SORT_FIELDS = {"name", "latest", "activity_days", "member_count", "result_count", "support_amount"}


def _filtered(queryset, *, date_field, start_date, end_date, department_id, site_id=None):
    queryset = queryset.filter(
        activity_site__isnull=False,
        **{f"{date_field}__range": (start_date, end_date)},
    )
    if department_id:
        queryset = queryset.filter(department_id=department_id)
    if site_id:
        queryset = queryset.filter(activity_site_id=site_id)
    return queryset


def _add_totals(rows, totals_by_site, fields, multiplier=1):
    for row in rows:
        site_id = row["activity_site_id"]
        totals = totals_by_site[site_id]
        totals["site_id"] = site_id
        totals["site_name"] = row["activity_site__canonical_name"]
        for field in fields:
            totals[field] += multiplier * int(row.get(f"sum_{field}") or 0)


def build_activity_site_comparison(
    *, start_date, end_date, department_id=None, site_id=None, sort="support_amount", direction="desc"
):
    """Build per-site final actuals with a fixed six-query plan (no per-site queries)."""
    totals_by_site = defaultdict(
        lambda: {
            "approach_count": 0,
            "communication_count": 0,
            "result_count": 0,
            "support_amount": 0,
            "cs_count": 0,
            "refugee_count": 0,
            "return_postal_count": 0,
            "return_postal_amount": 0,
            "return_qr_count": 0,
            "return_qr_amount": 0,
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
            site_id=site_id,
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
        totals["result_count"] += totals["return_postal_count"] + totals["return_qr_count"]
        totals["support_amount"] += totals["return_postal_amount"] + totals["return_qr_amount"]
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


def _history_values(
    queryset,
    *,
    date_field,
    source_label,
    source_code,
    note_field,
    multiplier=1,
    result_expression=None,
    amount_expression=None,
):
    result_expression = result_expression or F("result_count")
    amount_expression = amount_expression or F("support_amount")
    signed_result = ExpressionWrapper(Value(multiplier) * result_expression, output_field=IntegerField())
    signed_amount = ExpressionWrapper(Value(multiplier) * amount_expression, output_field=IntegerField())
    return (
        queryset.order_by()
        .annotate(
            history_date=F(date_field),
            history_source=Value(source_label, output_field=CharField()),
            history_source_code=source_code,
            history_member=F("member__name"),
            history_department=F("department__code"),
            history_result=signed_result,
            history_amount=signed_amount,
            history_approach=F("approach_count") if multiplier > 0 else Value(0, output_field=IntegerField()),
            history_communication=(
                F("communication_count") if multiplier > 0 else Value(0, output_field=IntegerField())
            ),
            history_note=F(note_field),
        )
        .values(
            "history_date",
            "history_source",
            "history_source_code",
            "history_member",
            "history_department",
            "history_result",
            "history_amount",
            "history_approach",
            "history_communication",
            "history_note",
        )
    )


def activity_site_history_queryset(*, site_id, start_date, end_date, department_id=None):
    common = {
        "start_date": start_date,
        "end_date": end_date,
        "department_id": department_id,
        "site_id": site_id,
    }
    entries = _history_values(
        _filtered(MemberDailyMetricEntry.objects.all(), date_field="entry_date", **common),
        date_field="entry_date",
        source_label="日次入力",
        source_code=Value("entry", output_field=CharField()),
        note_field="memo",
    )
    adjustments = _history_values(
        _filtered(MetricAdjustment.objects.all(), date_field="target_date", **common),
        date_field="target_date",
        source_label="補正",
        source_code=F("source_type"),
        note_field="note",
        result_expression=F("result_count") + F("return_postal_count") + F("return_qr_count"),
        amount_expression=F("support_amount") + F("return_postal_amount") + F("return_qr_amount"),
    )
    cancellations = _history_values(
        _filtered(WVMetricCancellation.objects.all(), date_field="target_date", **common),
        date_field="target_date",
        source_label="WVキャンセル",
        source_code=Value("cancellation", output_field=CharField()),
        note_field="comment",
        multiplier=-1,
    )
    return entries.union(adjustments, cancellations, all=True).order_by(
        "-history_date", "history_member", "history_source", "history_department"
    )
