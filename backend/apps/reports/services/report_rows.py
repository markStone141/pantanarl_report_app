from __future__ import annotations

from django.http import HttpRequest

from apps.dairymetrics.models import MemberDailyMetricEntry

from apps.reports.models import DailyDepartmentReport


EMPTY_REPORT_ROW = {
    "member_id": "",
    "amount": "0",
    "count": "0",
    "cs_count": "0",
    "refugee_count": "0",
    "location": "",
}


def empty_report_rows() -> list[dict[str, str]]:
    return [EMPTY_REPORT_ROW.copy()]


def build_row_values(*, request: HttpRequest) -> list[dict[str, str]]:
    member_ids = request.POST.getlist("member_ids")
    amounts = request.POST.getlist("amounts")
    counts = request.POST.getlist("counts")
    cs_counts = request.POST.getlist("cs_counts")
    refugee_counts = request.POST.getlist("refugee_counts")
    locations = request.POST.getlist("locations")
    size = max(len(member_ids), len(amounts), len(counts), len(cs_counts), len(refugee_counts), len(locations), 1)
    rows = []
    for i in range(size):
        rows.append(
            {
                "member_id": member_ids[i] if i < len(member_ids) else "",
                "amount": amounts[i] if i < len(amounts) else "0",
                "count": counts[i] if i < len(counts) else "0",
                "cs_count": cs_counts[i] if i < len(cs_counts) else "0",
                "refugee_count": refugee_counts[i] if i < len(refugee_counts) else "0",
                "location": locations[i] if i < len(locations) else "",
            }
        )
    return rows


def parse_rows(*, rows, allowed_member_ids, split_counts=False):
    parsed_rows = []
    row_errors = []
    for idx, row in enumerate(rows, start=1):
        member_id_str = row["member_id"].strip()
        amount_str = row["amount"].strip() or "0"
        count_str = row["count"].strip() or "0"
        cs_count_str = row["cs_count"].strip() or "0"
        refugee_count_str = row["refugee_count"].strip() or "0"
        location = row["location"].strip()
        if not member_id_str:
            continue

        if not member_id_str.isdigit() or int(member_id_str) not in allowed_member_ids:
            row_errors.append(f"{idx}行目: メンバーが不正です。")
            continue

        try:
            amount = int(amount_str)
            if split_counts:
                cs_count = int(cs_count_str)
                refugee_count = int(refugee_count_str)
                count = cs_count + refugee_count
            else:
                count = int(count_str)
                cs_count = 0
                refugee_count = 0
        except ValueError:
            row_errors.append(f"{idx}行目: 金額と件数は数値で入力してください。")
            continue

        if amount < 0 or count < 0 or cs_count < 0 or refugee_count < 0:
            row_errors.append(f"{idx}行目: 金額と件数は0以上で入力してください。")
            continue

        parsed_rows.append(
            {
                "member_id": int(member_id_str),
                "amount": amount,
                "count": count,
                "cs_count": cs_count,
                "refugee_count": refugee_count,
                "location": location,
            }
        )

    if not parsed_rows:
        row_errors.append("メンバー行を1行以上入力してください。")

    return parsed_rows, row_errors


def build_initial_rows_from_report(report: DailyDepartmentReport) -> list[dict[str, str]]:
    rows = []
    for line in report.lines.select_related("member").all():
        rows.append(
            {
                "member_id": str(line.member_id) if line.member_id else "",
                "amount": str(line.amount),
                "count": str(line.count),
                "cs_count": str(line.cs_count),
                "refugee_count": str(line.refugee_count),
                "location": line.location,
            }
        )
    return rows or empty_report_rows()


def build_initial_row_from_metric_entry(
    *,
    entry: MemberDailyMetricEntry,
    split_counts: bool,
    show_location: bool,
) -> dict[str, str]:
    return {
        "member_id": str(entry.member_id) if entry.member_id else "",
        "amount": str(entry.support_amount),
        "count": str(entry.result_count),
        "cs_count": str(entry.cs_count),
        "refugee_count": str(entry.refugee_count),
        "location": entry.location_name if show_location else "",
    }
