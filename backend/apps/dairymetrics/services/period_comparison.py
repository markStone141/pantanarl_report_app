"""Compare completed route ordinals across months using normal daily entries."""
from collections import defaultdict
from datetime import timedelta
import re
import unicodedata

from django.utils import timezone

from apps.dairymetrics.models import MemberDailyMetricEntry
from apps.targets.models import DepartmentPeriodTarget, Period, PeriodTargetMetricValue
from .metrics_v2 import _build_summary_cards, _count_value


def _route_key(name):
    name = unicodedata.normalize("NFKC", name).strip()
    match = re.search(r"第\s*([0-9]+|[一二三四五六七八九十]+)\s*次", name)
    if not match:
        return (1, name), name
    number = match[1]
    if not number.isdigit():
        digits = {letter: i for i, letter in enumerate("〇一二三四五六七八九", 0)}
        if "十" in number:
            tens, ones = number.split("十", 1)
            number = 10 * digits.get(tens, 1) + digits.get(ones, 0)
        else:
            number = digits.get(number)
    if number is None:
        return (1, name), name
    number = int(number)
    return (0, number), f"第{number}次路程"


def build_period_comparison(*, department, reference_date, months=6):
    end = min(reference_date, timezone.localdate() - timedelta(days=1))
    index = reference_date.year * 12 + reference_date.month - months
    start = reference_date.replace(year=index // 12, month=index % 12 + 1, day=1)
    periods = list(Period.objects.filter(
        month__gte=start, month__lte=reference_date.replace(day=1), end_date__lte=end,
    ).exclude(status="planned").order_by("month", "start_date", "id"))
    result = {"months": months, "start": start, "end": end, "columns": [], "rows": []}
    if not periods:
        return result
    entries = MemberDailyMetricEntry.objects.filter(
        department=department,
        entry_date__range=(min(p.start_date for p in periods), max(p.end_date for p in periods)),
    ).values("entry_date", "member_id", "support_amount", "result_count",
             "approach_count", "communication_count", "cs_count", "refugee_count")
    by_day = defaultdict(list)
    for entry in entries:
        by_day[entry["entry_date"]].append(entry)
    targets = dict(DepartmentPeriodTarget.objects.filter(
        department=department, period__in=periods,
    ).values_list("period_id", "target_amount"))
    targets.update(dict(PeriodTargetMetricValue.objects.filter(
        department=department, period__in=periods, metric__code="amount",
    ).values_list("period_id", "value")))
    groups = {}
    fields = ("support_amount", "result_count", "approach_count", "communication_count",
              "cs_count", "refugee_count")
    for period in periods:
        route_entries = []
        day = period.start_date
        while day <= period.end_date:
            route_entries.extend(by_day.get(day, []))
            day += timedelta(days=1)
        if not route_entries:
            continue
        key, label = _route_key(period.name)
        group = groups.setdefault(key, {"label": label, "entries": {}, "periods": [], "target": 0})
        group["entries"].update({(e["entry_date"], e["member_id"]): e for e in route_entries})
        group["periods"].append(f"{period.month:%Y/%m} {period.name}")
        group["target"] += targets.get(period.pk, 0)
    for key in sorted(groups):
        group = groups[key]
        data = list(group["entries"].values())
        totals = {field: sum(e[field] for e in data) for field in fields}
        days = len({e["entry_date"] for e in data})
        workers = len(data)
        members = len({e["member_id"] for e in data})
        summary = _build_summary_cards(
            title_prefix="", department_code=department.code, totals=totals,
            target_amount=group["target"], active_days=days,
            average_work_count=workers, average_member_count=members,
        )
        values = [f"{len(group['periods'])}路程", f"{totals['support_amount']:,}円",
                  f"{_count_value(department.code, totals):,}件"]
        if department.code == "WV":
            values += [f"{totals['cs_count']:,}件", f"{totals['refugee_count']:,}件"]
        values += [f"{totals['approach_count']:,}", f"{totals['communication_count']:,}",
                   f"{days}日", f"{workers}人日", f"{members}人",
                   f"{totals['support_amount'] / workers:,.0f}円"]
        values += [r["value"] for r in summary["rates"]]
        values += [r["value"] for r in summary["averages"]]
        result["columns"].append({"label": group["label"], "periods": group["periods"], "values": values})
    labels = ["対象路程数", "通常実績金額", "通常実績件数"]
    if department.code == "WV":
        labels += ["CS件数", "難民件数"]
    labels += ["AP合計", "CM合計", "稼働日合計", "延べ稼働人数", "稼働メンバー実人数",
               "稼働メンバー1人あたりの平均金額", "決済率", "コミュニケーション率"]
    labels += ["1稼働あたりの平均AP", "1稼働あたりの平均CM", "1稼働あたりの平均件数",
               "1稼働あたりの平均金額", "1決済あたりの平均金額", "目標進捗"]
    result["rows"] = [{"label": label, "values": [c["values"][i] for c in result["columns"]]}
                      for i, label in enumerate(labels)]
    return result
