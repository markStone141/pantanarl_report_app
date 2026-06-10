from django.db.models import Sum

from apps.dairymetrics.models import MemberDailyMetricEntry, MetricAdjustment

ENTRY_METRIC_FIELDS = [
    "approach_count",
    "communication_count",
    "result_count",
    "support_amount",
    "cs_count",
    "refugee_count",
]

ADJUSTMENT_METRIC_FIELDS = [
    "approach_count",
    "communication_count",
    "result_count",
    "support_amount",
    "return_postal_count",
    "return_postal_amount",
    "return_qr_count",
    "return_qr_amount",
    "cs_count",
    "refugee_count",
]


def zero_final_actual_totals():
    return {field: 0 for field in {*ENTRY_METRIC_FIELDS, *ADJUSTMENT_METRIC_FIELDS}}


def _aggregate_queryset(queryset, fields):
    aggregated = queryset.aggregate(**{field: Sum(field) for field in fields})
    return {field: int(aggregated.get(field) or 0) for field in fields}


def aggregate_entry_box_totals(entries):
    return _aggregate_queryset(entries, ENTRY_METRIC_FIELDS)


def aggregate_adjustment_totals(adjustments):
    return _aggregate_queryset(adjustments, ADJUSTMENT_METRIC_FIELDS)


def merge_final_actual_totals(entry_totals=None, adjustment_totals=None):
    totals = zero_final_actual_totals()
    entry_totals = entry_totals or {}
    adjustment_totals = adjustment_totals or {}

    for field in ENTRY_METRIC_FIELDS:
        totals[field] = int(entry_totals.get(field) or 0)

    for field in ADJUSTMENT_METRIC_FIELDS:
        totals[field] = int(totals.get(field) or 0) + int(adjustment_totals.get(field) or 0)

    return totals


def collect_member_final_actual_totals(member, department, start_date, end_date, *, include_adjustments=True):
    entries = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date__range=(start_date, end_date),
    )
    entry_totals = aggregate_entry_box_totals(entries)
    adjustment_totals = {}
    if include_adjustments:
        adjustments = MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date__range=(start_date, end_date),
        )
        adjustment_totals = aggregate_adjustment_totals(adjustments)
    return merge_final_actual_totals(entry_totals, adjustment_totals)


def collect_department_final_actual_totals(department, start_date, end_date, *, include_adjustments=True):
    entries = MemberDailyMetricEntry.objects.filter(
        department=department,
        entry_date__range=(start_date, end_date),
    )
    entry_totals = aggregate_entry_box_totals(entries)
    adjustment_totals = {}
    if include_adjustments:
        adjustments = MetricAdjustment.objects.filter(
            department=department,
            target_date__range=(start_date, end_date),
        )
        adjustment_totals = aggregate_adjustment_totals(adjustments)
    return merge_final_actual_totals(entry_totals, adjustment_totals)


def collect_increase_adjustment_totals(*, department, start_date, end_date, member=None):
    adjustments = MetricAdjustment.objects.filter(
        department=department,
        target_date__range=(start_date, end_date),
        source_type=MetricAdjustment.SOURCE_INCREASE,
    )
    if member is not None:
        adjustments = adjustments.filter(member=member)
    return aggregate_adjustment_totals(adjustments)


def collect_increase_adjustment_totals_by_member_ids(*, member_ids, department, start_date, end_date):
    totals_by_member_id = {member_id: zero_final_actual_totals() for member_id in member_ids}
    if not member_ids:
        return totals_by_member_id

    adjustment_annotations = {f"sum_{field}": Sum(field) for field in ADJUSTMENT_METRIC_FIELDS}
    adjustment_rows = (
        MetricAdjustment.objects.filter(
            member_id__in=member_ids,
            department=department,
            target_date__range=(start_date, end_date),
            source_type=MetricAdjustment.SOURCE_INCREASE,
        )
        .values("member_id")
        .annotate(**adjustment_annotations)
    )
    for row in adjustment_rows:
        totals = totals_by_member_id.setdefault(row["member_id"], zero_final_actual_totals())
        for field in ADJUSTMENT_METRIC_FIELDS:
            totals[field] = int(row.get(f"sum_{field}") or 0)

    return totals_by_member_id


def collect_member_final_actual_totals_by_ids(
    *,
    member_ids,
    department,
    start_date,
    end_date,
    include_adjustments=True,
):
    totals_by_member_id = {member_id: zero_final_actual_totals() for member_id in member_ids}
    if not member_ids:
        return totals_by_member_id

    entry_annotations = {f"sum_{field}": Sum(field) for field in ENTRY_METRIC_FIELDS}
    entry_rows = (
        MemberDailyMetricEntry.objects.filter(
            member_id__in=member_ids,
            department=department,
            entry_date__range=(start_date, end_date),
        )
        .values("member_id")
        .annotate(**entry_annotations)
    )
    for row in entry_rows:
        totals = totals_by_member_id.setdefault(row["member_id"], zero_final_actual_totals())
        for field in ENTRY_METRIC_FIELDS:
            totals[field] = int(row.get(f"sum_{field}") or 0)

    if not include_adjustments:
        return totals_by_member_id

    adjustment_annotations = {f"sum_{field}": Sum(field) for field in ADJUSTMENT_METRIC_FIELDS}
    adjustment_rows = (
        MetricAdjustment.objects.filter(
            member_id__in=member_ids,
            department=department,
            target_date__range=(start_date, end_date),
        )
        .values("member_id")
        .annotate(**adjustment_annotations)
    )
    for row in adjustment_rows:
        totals = totals_by_member_id.setdefault(row["member_id"], zero_final_actual_totals())
        for field in ADJUSTMENT_METRIC_FIELDS:
            totals[field] = int(totals.get(field) or 0) + int(row.get(f"sum_{field}") or 0)

    return totals_by_member_id


def collect_department_final_actual_totals_by_codes(*, target_codes, start_date, end_date, include_adjustments=True):
    totals_by_code = {code: zero_final_actual_totals() for code in target_codes}
    if not target_codes:
        return totals_by_code

    entry_annotations = {f"sum_{field}": Sum(field) for field in ENTRY_METRIC_FIELDS}
    entry_rows = (
        MemberDailyMetricEntry.objects.filter(
            department__code__in=target_codes,
            entry_date__range=(start_date, end_date),
        )
        .values("department__code")
        .annotate(**entry_annotations)
    )
    for row in entry_rows:
        code = row["department__code"]
        totals = totals_by_code.setdefault(code, zero_final_actual_totals())
        for field in ENTRY_METRIC_FIELDS:
            totals[field] = int(row.get(f"sum_{field}") or 0)

    if not include_adjustments:
        return totals_by_code

    adjustment_annotations = {f"sum_{field}": Sum(field) for field in ADJUSTMENT_METRIC_FIELDS}
    adjustment_rows = (
        MetricAdjustment.objects.filter(
            department__code__in=target_codes,
            target_date__range=(start_date, end_date),
        )
        .values("department__code")
        .annotate(**adjustment_annotations)
    )
    for row in adjustment_rows:
        code = row["department__code"]
        totals = totals_by_code.setdefault(code, zero_final_actual_totals())
        for field in ADJUSTMENT_METRIC_FIELDS:
            totals[field] = int(totals.get(field) or 0) + int(row.get(f"sum_{field}") or 0)

    return totals_by_code
