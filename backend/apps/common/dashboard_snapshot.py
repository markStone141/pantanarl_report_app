from django.utils import timezone

from apps.common.report_metrics import SPLIT_COUNT_CODES, STATUS_NOT_SUBMITTED, STATUS_SUBMITTED
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine


def list_target_codes(target_departments):
    return [code for code, _ in target_departments]


def build_submission_snapshot(*, report_date, target_departments):
    target_codes = list_target_codes(target_departments)
    reports_query = DailyDepartmentReport.objects.filter(
        report_date=report_date,
    ).select_related("department", "reporter")
    if target_codes:
        reports_query = reports_query.filter(department__code__in=target_codes)
    else:
        reports_query = reports_query.none()
    reports = list(reports_query.order_by("department__code", "-created_at"))

    report_totals = {
        code: {"count": 0, "amount": 0}
        for code in target_codes
    }
    latest_by_code = {}
    for report in reports:
        code = report.department.code
        if code not in report_totals:
            continue
        report_totals[code]["count"] += report.total_count
        report_totals[code]["amount"] += report.followup_count
        if code not in latest_by_code:
            latest_by_code[code] = report

    submission_rows = []
    daily_totals = {}
    for code, label in target_departments:
        latest = latest_by_code.get(code)
        totals = report_totals.get(code, {"count": 0, "amount": 0})
        if latest:
            submission_rows.append(
                {
                    "code": code,
                    "label": label,
                    "reporter_name": latest.reporter.name if latest.reporter else "-",
                    "submitted_time": timezone.localtime(latest.created_at).strftime("%H:%M"),
                    "status": STATUS_SUBMITTED,
                    "count": totals["count"],
                    "amount": totals["amount"],
                    "report_id": latest.id,
                    "has_split_counts": code in SPLIT_COUNT_CODES,
                    "cs_count": 0,
                    "refugee_count": 0,
                }
            )
        else:
            submission_rows.append(
                {
                    "code": code,
                    "label": label,
                    "reporter_name": "-",
                    "submitted_time": "-",
                    "status": STATUS_NOT_SUBMITTED,
                    "count": "-",
                    "amount": "-",
                    "report_id": None,
                    "has_split_counts": code in SPLIT_COUNT_CODES,
                    "cs_count": "-",
                    "refugee_count": "-",
                }
            )
        daily_totals[code] = {
            "count": totals["count"],
            "amount": totals["amount"],
            "cs_count": 0,
            "refugee_count": 0,
        }

    lines_query = DailyDepartmentReportLine.objects.filter(
        report__report_date=report_date,
    ).select_related("member", "report__department")
    if target_codes:
        lines_query = lines_query.filter(report__department__code__in=target_codes)
    else:
        lines_query = lines_query.none()

    member_totals = {code: {} for code in target_codes}
    line_totals = {code: {"cs_count": 0, "refugee_count": 0} for code in target_codes}
    for line in lines_query:
        code = line.report.department.code
        if code not in member_totals:
            continue
        member_name = line.member.name if line.member else "-"
        if member_name not in member_totals[code]:
            member_totals[code][member_name] = {
                "member_name": member_name,
                "count": 0,
                "amount": 0,
                "cs_count": 0,
                "refugee_count": 0,
            }
        member_totals[code][member_name]["count"] += line.count
        member_totals[code][member_name]["amount"] += line.amount
        member_totals[code][member_name]["cs_count"] += line.cs_count
        member_totals[code][member_name]["refugee_count"] += line.refugee_count
        line_totals[code]["cs_count"] += line.cs_count
        line_totals[code]["refugee_count"] += line.refugee_count

    for code in target_codes:
        daily_totals[code]["cs_count"] = line_totals[code]["cs_count"]
        daily_totals[code]["refugee_count"] = line_totals[code]["refugee_count"]
    for row in submission_rows:
        if row["has_split_counts"] and row["count"] != "-":
            code = row["code"]
            row["cs_count"] = line_totals[code]["cs_count"]
            row["refugee_count"] = line_totals[code]["refugee_count"]

    return {
        "target_codes": target_codes,
        "submission_rows": submission_rows,
        "daily_totals": daily_totals,
        "member_totals": member_totals,
    }


def build_member_rows(*, member_totals, codes):
    merged = {}
    for code in codes:
        for member_name, totals in member_totals.get(code, {}).items():
            if member_name not in merged:
                merged[member_name] = {
                    "member_name": member_name,
                    "count": 0,
                    "amount": 0,
                    "cs_count": 0,
                    "refugee_count": 0,
                }
            merged[member_name]["count"] += totals["count"]
            merged[member_name]["amount"] += totals["amount"]
            merged[member_name]["cs_count"] += totals["cs_count"]
            merged[member_name]["refugee_count"] += totals["refugee_count"]
    return sorted(
        merged.values(),
        key=lambda row: (-row["amount"], -row["count"], row["member_name"]),
    )
