from __future__ import annotations

from django.db.models import Sum

from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MetricAdjustment


EMPTY_ADJUSTMENT_TOTALS = {
    "result_count": 0,
    "support_amount": 0,
    "return_postal_count": 0,
    "return_postal_amount": 0,
    "return_qr_count": 0,
    "return_qr_amount": 0,
    "cs_count": 0,
    "refugee_count": 0,
}


def build_adjustment_totals_map(entries):
    entries = list(entries)
    if not entries:
        return {}
    member_ids = {entry.member_id for entry in entries}
    department_ids = {entry.department_id for entry in entries}
    dates = {entry.entry_date for entry in entries}
    rows = (
        MetricAdjustment.objects.filter(
            member_id__in=member_ids,
            department_id__in=department_ids,
            target_date__in=dates,
        )
        .values("member_id", "department_id", "target_date")
        .annotate(
            result_count_total=Sum("result_count"),
            support_amount_total=Sum("support_amount"),
            return_postal_count_total=Sum("return_postal_count"),
            return_postal_amount_total=Sum("return_postal_amount"),
            return_qr_count_total=Sum("return_qr_count"),
            return_qr_amount_total=Sum("return_qr_amount"),
            cs_count_total=Sum("cs_count"),
            refugee_count_total=Sum("refugee_count"),
        )
    )
    totals_map = {}
    for row in rows:
        totals_map[(row["member_id"], row["department_id"], row["target_date"])] = {
            "result_count": int(row["result_count_total"] or 0),
            "support_amount": int(row["support_amount_total"] or 0),
            "return_postal_count": int(row["return_postal_count_total"] or 0),
            "return_postal_amount": int(row["return_postal_amount_total"] or 0),
            "return_qr_count": int(row["return_qr_count_total"] or 0),
            "return_qr_amount": int(row["return_qr_amount_total"] or 0),
            "cs_count": int(row["cs_count_total"] or 0),
            "refugee_count": int(row["refugee_count_total"] or 0),
        }
    return totals_map


def entry_final_count_value(*, entry, adjustment_totals):
    if entry.department.code == "WV":
        return (
            int(entry.cs_count or 0)
            + int(entry.refugee_count or 0)
            + int(adjustment_totals["cs_count"])
            + int(adjustment_totals["refugee_count"])
        )
    return (
        int(entry.result_count or 0)
        + int(adjustment_totals["result_count"])
        + int(adjustment_totals["return_postal_count"])
        + int(adjustment_totals["return_qr_count"])
    )


def entry_final_amount_value(*, entry, adjustment_totals):
    return (
        int(entry.support_amount or 0)
        + int(adjustment_totals["support_amount"])
        + int(adjustment_totals["return_postal_amount"])
        + int(adjustment_totals["return_qr_amount"])
    )


def build_member_activity_trend(*, member, department, start_date=None, end_date=None):
    entry_queryset = MemberDailyMetricEntry.objects.select_related("department").filter(member=member, department=department)
    adjustment_queryset = MetricAdjustment.objects.filter(member=member, department=department)
    if start_date is not None and end_date is not None:
        entry_queryset = entry_queryset.filter(entry_date__range=(start_date, end_date))
        adjustment_queryset = adjustment_queryset.filter(target_date__range=(start_date, end_date))
        latest_entry_dates = list(entry_queryset.order_by("entry_date").values_list("entry_date", flat=True).distinct())
        latest_adjustment_dates = list(adjustment_queryset.order_by("target_date").values_list("target_date", flat=True).distinct())
    else:
        latest_entry_dates = list(entry_queryset.order_by("-entry_date").values_list("entry_date", flat=True).distinct()[:120])
        latest_entry_dates.reverse()
        latest_adjustment_dates = list(adjustment_queryset.order_by("-target_date").values_list("target_date", flat=True).distinct()[:120])
        latest_adjustment_dates.reverse()
    latest_dates = sorted(set(latest_entry_dates) | set(latest_adjustment_dates))
    if start_date is None and end_date is None and len(latest_dates) > 120:
        latest_dates = latest_dates[-120:]
    if not latest_dates:
        return {
            "labels": [],
            "amounts": [],
            "counts": [],
            "has_data": False,
            "count_label": "件数",
            "default_visible_count": 0,
        }
    latest_entries = list(entry_queryset.filter(entry_date__in=latest_dates).order_by("entry_date", "id"))
    entry_by_date = {entry.entry_date: entry for entry in latest_entries}
    adjustment_totals_map = build_adjustment_totals_map(latest_entries)
    adjustment_only_rows = (
        adjustment_queryset.filter(target_date__in=latest_dates)
        .values("target_date")
        .annotate(
            result_count_total=Sum("result_count"),
            support_amount_total=Sum("support_amount"),
            return_postal_count_total=Sum("return_postal_count"),
            return_postal_amount_total=Sum("return_postal_amount"),
            return_qr_count_total=Sum("return_qr_count"),
            return_qr_amount_total=Sum("return_qr_amount"),
            cs_count_total=Sum("cs_count"),
            refugee_count_total=Sum("refugee_count"),
        )
    )
    adjustment_only_map = {
        row["target_date"]: {
            "result_count": int(row["result_count_total"] or 0),
            "support_amount": int(row["support_amount_total"] or 0),
            "return_postal_count": int(row["return_postal_count_total"] or 0),
            "return_postal_amount": int(row["return_postal_amount_total"] or 0),
            "return_qr_count": int(row["return_qr_count_total"] or 0),
            "return_qr_amount": int(row["return_qr_amount_total"] or 0),
            "cs_count": int(row["cs_count_total"] or 0),
            "refugee_count": int(row["refugee_count_total"] or 0),
        }
        for row in adjustment_only_rows
    }
    labels = []
    amounts = []
    counts = []
    adjustment_amounts = []
    adjustment_counts = []
    approach_counts = []
    communication_counts = []
    target_amounts = []
    rate_values = []
    for activity_date in latest_dates:
        entry = entry_by_date.get(activity_date)
        if entry is not None:
            adjustment_totals = adjustment_totals_map.get(
                (entry.member_id, entry.department_id, entry.entry_date),
                EMPTY_ADJUSTMENT_TOTALS,
            )
        else:
            adjustment_totals = adjustment_only_map.get(activity_date, EMPTY_ADJUSTMENT_TOTALS)
        labels.append(activity_date.strftime("%m/%d"))
        if entry is not None:
            amount_value = entry_final_amount_value(entry=entry, adjustment_totals=adjustment_totals)
        else:
            amount_value = (
                int(adjustment_totals["support_amount"])
                + int(adjustment_totals["return_postal_amount"])
                + int(adjustment_totals["return_qr_amount"])
            )
        amounts.append(amount_value)
        adjustment_amount_value = (
            int(adjustment_totals["support_amount"])
            + int(adjustment_totals["return_postal_amount"])
            + int(adjustment_totals["return_qr_amount"])
        )
        adjustment_amounts.append(adjustment_amount_value)
        if department.code == "WV":
            adjustment_count_value = int(adjustment_totals["cs_count"]) + int(adjustment_totals["refugee_count"])
        else:
            adjustment_count_value = (
                int(adjustment_totals["result_count"])
                + int(adjustment_totals["return_postal_count"])
                + int(adjustment_totals["return_qr_count"])
            )
        if entry is not None:
            counts.append(entry_final_count_value(entry=entry, adjustment_totals=adjustment_totals))
            approach_counts.append(int(entry.approach_count or 0))
            communication_counts.append(int(entry.communication_count or 0))
            target_amount = int(entry.daily_target_amount or 0)
        else:
            counts.append(adjustment_count_value)
            approach_counts.append(0)
            communication_counts.append(0)
            target_amount = 0
        adjustment_counts.append(adjustment_count_value)
        target_amounts.append(target_amount)
        rate_values.append(round((amount_value / target_amount) * 100, 1) if target_amount > 0 else None)
    return {
        "labels": labels,
        "amounts": amounts,
        "counts": counts,
        "adjustment_amounts": adjustment_amounts,
        "adjustment_counts": adjustment_counts,
        "approach_counts": approach_counts,
        "communication_counts": communication_counts,
        "target_amounts": target_amounts,
        "rate_values": rate_values,
        "has_data": True,
        "count_label": "件数" if department.code != "WV" else "件数相当",
        "default_visible_count": min(30, len(labels)),
    }


def build_overall_activity_trend(*, department=None, start_date=None, end_date=None):
    entry_queryset = MemberDailyMetricEntry.objects.all()
    adjustment_queryset = MetricAdjustment.objects.all()
    if department is not None:
        entry_queryset = entry_queryset.filter(department=department)
        adjustment_queryset = adjustment_queryset.filter(department=department)
    if start_date is not None and end_date is not None:
        entry_queryset = entry_queryset.filter(entry_date__range=(start_date, end_date))
        adjustment_queryset = adjustment_queryset.filter(target_date__range=(start_date, end_date))
        latest_dates = list(entry_queryset.order_by("entry_date").values_list("entry_date", flat=True).distinct())
    else:
        latest_dates = list(entry_queryset.order_by("-entry_date").values_list("entry_date", flat=True).distinct()[:120])
        latest_dates.reverse()
    if not latest_dates:
        return {
            "labels": [],
            "amounts": [],
            "counts": [],
            "approach_counts": [],
            "communication_counts": [],
            "target_amounts": [],
            "rate_values": [],
            "has_data": False,
            "count_label": "件数",
            "default_visible_count": 0,
        }
    entry_totals = {
        row["entry_date"]: row
        for row in entry_queryset.filter(entry_date__in=latest_dates)
        .values("entry_date")
        .annotate(
            result_count_total=Sum("result_count"),
            support_amount_total=Sum("support_amount"),
            approach_count_total=Sum("approach_count"),
            communication_count_total=Sum("communication_count"),
            cs_count_total=Sum("cs_count"),
            refugee_count_total=Sum("refugee_count"),
        )
    }
    adjustment_totals = {
        row["target_date"]: row
        for row in adjustment_queryset.filter(target_date__in=latest_dates)
        .values("target_date")
        .annotate(
            result_count_total=Sum("result_count"),
            support_amount_total=Sum("support_amount"),
            return_postal_count_total=Sum("return_postal_count"),
            return_postal_amount_total=Sum("return_postal_amount"),
            return_qr_count_total=Sum("return_qr_count"),
            return_qr_amount_total=Sum("return_qr_amount"),
            cs_count_total=Sum("cs_count"),
            refugee_count_total=Sum("refugee_count"),
        )
    }
    summary_queryset = DepartmentDailyMetricSummary.objects.filter(entry_date__in=latest_dates)
    if department is not None:
        summary_queryset = summary_queryset.filter(department=department)
    daily_target_totals = {
        row["entry_date"]: int(row["daily_target_amount_total"] or 0)
        for row in summary_queryset.values("entry_date").annotate(daily_target_amount_total=Sum("daily_target_amount"))
    }

    labels = []
    amounts = []
    counts = []
    approach_counts = []
    communication_counts = []
    target_amounts = []
    rate_values = []
    use_equivalent_count = department is None or department.code == "WV"
    for activity_date in latest_dates:
        entry_row = entry_totals.get(activity_date, {})
        adjustment_row = adjustment_totals.get(activity_date, {})
        labels.append(activity_date.strftime("%m/%d"))
        amount_value = (
            int(entry_row.get("support_amount_total") or 0)
            + int(adjustment_row.get("support_amount_total") or 0)
            + int(adjustment_row.get("return_postal_amount_total") or 0)
            + int(adjustment_row.get("return_qr_amount_total") or 0)
        )
        amounts.append(amount_value)
        if use_equivalent_count:
            counts.append(
                int(entry_row.get("result_count_total") or 0)
                + int(entry_row.get("cs_count_total") or 0)
                + int(entry_row.get("refugee_count_total") or 0)
                + int(adjustment_row.get("result_count_total") or 0)
                + int(adjustment_row.get("return_postal_count_total") or 0)
                + int(adjustment_row.get("return_qr_count_total") or 0)
                + int(adjustment_row.get("cs_count_total") or 0)
                + int(adjustment_row.get("refugee_count_total") or 0)
            )
        else:
            counts.append(
                int(entry_row.get("result_count_total") or 0)
                + int(adjustment_row.get("result_count_total") or 0)
                + int(adjustment_row.get("return_postal_count_total") or 0)
                + int(adjustment_row.get("return_qr_count_total") or 0)
            )
        approach_counts.append(int(entry_row.get("approach_count_total") or 0))
        communication_counts.append(int(entry_row.get("communication_count_total") or 0))
        target_amount = int(daily_target_totals.get(activity_date) or 0)
        target_amounts.append(target_amount)
        rate_values.append(round((amount_value / target_amount) * 100, 1) if target_amount > 0 else None)

    return {
        "labels": labels,
        "amounts": amounts,
        "counts": counts,
        "approach_counts": approach_counts,
        "communication_counts": communication_counts,
        "target_amounts": target_amounts,
        "rate_values": rate_values,
        "has_data": True,
        "count_label": "件数相当" if use_equivalent_count else "件数",
        "default_visible_count": min(30, len(labels)),
    }
