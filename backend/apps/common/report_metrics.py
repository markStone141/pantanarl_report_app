from apps.reports.models import DailyDepartmentReportLine

SPLIT_COUNT_CODES = {"WV"}
STATUS_SUBMITTED = "提出済み"
STATUS_NOT_SUBMITTED = "未提出"


def period_status(*, today, start_date, end_date) -> str:
    if start_date <= today <= end_date:
        return "active"
    if today < start_date:
        return "planned"
    return "finished"


def metric_actual_value(*, metric_code, total_count, total_amount, total_cs_count=0, total_refugee_count=0):
    if metric_code == "count":
        return total_count
    if metric_code == "cs_count":
        return total_cs_count
    if metric_code == "refugee_count":
        return total_refugee_count
    if metric_code == "amount":
        return total_amount
    return 0


def collect_actual_totals(*, start_date, end_date, target_codes):
    lines = (
        DailyDepartmentReportLine.objects.filter(
            report__report_date__gte=start_date,
            report__report_date__lte=end_date,
            report__department__code__in=target_codes,
        )
        .select_related("report__department")
        .values("report__department__code", "count", "amount", "cs_count", "refugee_count")
    )
    totals = {
        code: {"count": 0, "amount": 0, "cs_count": 0, "refugee_count": 0}
        for code in target_codes
    }
    for line in lines:
        code = line["report__department__code"]
        totals[code]["count"] += line["count"]
        totals[code]["amount"] += line["amount"]
        totals[code]["cs_count"] += line["cs_count"]
        totals[code]["refugee_count"] += line["refugee_count"]
    return totals


def format_metric_triples(*, metrics, target_values, actual_totals):
    if not metrics:
        return "-", "-", "-"
    target_parts = []
    actual_parts = []
    rate_parts = []
    for metric in metrics:
        label = metric.label
        unit = metric.unit or ""
        target = target_values.get(metric.id, 0)
        actual = metric_actual_value(
            metric_code=metric.code,
            total_count=actual_totals["count"],
            total_amount=actual_totals["amount"],
            total_cs_count=actual_totals.get("cs_count", 0),
            total_refugee_count=actual_totals.get("refugee_count", 0),
        )
        rate = f"{(actual / target) * 100:.1f}%" if target > 0 else "-"
        target_parts.append(f"{label} {target}{unit}")
        actual_parts.append(f"{label} {actual}{unit}")
        rate_parts.append(f"{label} {rate}")
    return " / ".join(target_parts), " / ".join(actual_parts), " / ".join(rate_parts)


def metric_detail_rows(*, metrics, target_values, actual_totals):
    rows = []
    for metric in metrics:
        target = target_values.get(metric.id, 0)
        actual = metric_actual_value(
            metric_code=metric.code,
            total_count=actual_totals["count"],
            total_amount=actual_totals["amount"],
            total_cs_count=actual_totals.get("cs_count", 0),
            total_refugee_count=actual_totals.get("refugee_count", 0),
        )
        rate = f"{(actual / target) * 100:.1f}%" if target > 0 else "-"
        rows.append(
            {
                "code": metric.code,
                "label": metric.label,
                "unit": metric.unit or "",
                "target": target,
                "actual": actual,
                "rate": rate,
            }
        )
    return rows


def format_yen(value: int) -> str:
    return f"{value:,}円"
