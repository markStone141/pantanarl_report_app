from __future__ import annotations

from django.db.models import Sum

from apps.dairymetrics.models import MetricAdjustment


def _normalized_adjustment_totals(row):
    return {
        "count": (
            int(row.get("result_count") or 0)
            + int(row.get("return_postal_count") or 0)
            + int(row.get("return_qr_count") or 0)
        ),
        "amount": (
            int(row.get("support_amount") or 0)
            + int(row.get("return_postal_amount") or 0)
            + int(row.get("return_qr_amount") or 0)
        ),
        "cs_count": int(row.get("cs_count") or 0),
        "refugee_count": int(row.get("refugee_count") or 0),
    }


def merge_adjustment_totals_into_department_totals(*, base_daily_totals, report_date, target_codes):
    totals_by_code = {
        code: {
            "count": int(base_daily_totals.get(code, {}).get("count", 0) or 0),
            "amount": int(base_daily_totals.get(code, {}).get("amount", 0) or 0),
            "cs_count": int(base_daily_totals.get(code, {}).get("cs_count", 0) or 0),
            "refugee_count": int(base_daily_totals.get(code, {}).get("refugee_count", 0) or 0),
        }
        for code in target_codes
    }
    adjustment_rows = (
        MetricAdjustment.objects.filter(
            target_date=report_date,
            department__code__in=target_codes,
        )
        .values("department__code")
        .annotate(
            result_count=Sum("result_count"),
            support_amount=Sum("support_amount"),
            return_postal_count=Sum("return_postal_count"),
            return_postal_amount=Sum("return_postal_amount"),
            return_qr_count=Sum("return_qr_count"),
            return_qr_amount=Sum("return_qr_amount"),
            cs_count=Sum("cs_count"),
            refugee_count=Sum("refugee_count"),
        )
    )
    for row in adjustment_rows:
        code = row["department__code"]
        totals = totals_by_code.setdefault(
            code,
            {"count": 0, "amount": 0, "cs_count": 0, "refugee_count": 0},
        )
        adjustment_totals = _normalized_adjustment_totals(row)
        for key, value in adjustment_totals.items():
            totals[key] += value
    return totals_by_code


def merge_adjustment_totals_into_member_totals(*, base_member_totals, report_date, target_codes):
    member_totals = {
        code: {
            member_name: {
                "member_name": row["member_name"],
                "count": int(row.get("count", 0) or 0),
                "amount": int(row.get("amount", 0) or 0),
                "cs_count": int(row.get("cs_count", 0) or 0),
                "refugee_count": int(row.get("refugee_count", 0) or 0),
                "input_order": row.get("input_order"),
            }
            for member_name, row in base_member_totals.get(code, {}).items()
        }
        for code in target_codes
    }

    adjustment_rows = (
        MetricAdjustment.objects.filter(
            target_date=report_date,
            department__code__in=target_codes,
        )
        .values("department__code", "member__name")
        .annotate(
            result_count=Sum("result_count"),
            support_amount=Sum("support_amount"),
            return_postal_count=Sum("return_postal_count"),
            return_postal_amount=Sum("return_postal_amount"),
            return_qr_count=Sum("return_qr_count"),
            return_qr_amount=Sum("return_qr_amount"),
            cs_count=Sum("cs_count"),
            refugee_count=Sum("refugee_count"),
        )
    )
    for row in adjustment_rows:
        code = row["department__code"]
        member_name = row["member__name"] or "-"
        member_row = member_totals[code].setdefault(
            member_name,
            {
                "member_name": member_name,
                "count": 0,
                "amount": 0,
                "cs_count": 0,
                "refugee_count": 0,
                "input_order": None,
            },
        )
        adjustment_totals = _normalized_adjustment_totals(row)
        for key, value in adjustment_totals.items():
            member_row[key] += value

    return member_totals
