"""Compare completed route ordinals across months using normal daily entries."""
from collections import defaultdict
from datetime import timedelta
import re
import unicodedata

from django.utils import timezone

from apps.dairymetrics.models import MemberDailyMetricEntry
from apps.targets.models import DepartmentPeriodTarget, Period, PeriodTargetMetricValue
from .metrics_v2 import _count_value, _format_number, _percentage, _safe_average


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


def comparison_metrics(department_code):
    fields = [("対象路程数", "路程"), ("通常実績金額", "円"), ("通常実績件数", "件")]
    if department_code == "WV":
        fields += [("CS件数", "件"), ("難民件数", "件")]
    fields += [("AP合計", ""), ("CM合計", ""), ("稼働日合計", "日"),
               ("延べ稼働人数", "人/日"), ("稼働メンバー実人数", "人"),
               ("稼働メンバー1人あたりの平均金額", "円"), ("決済率", "%"),
               ("コミュニケーション率", "%"), ("1稼働あたりの平均AP", ""),
               ("1稼働あたりの平均CM", ""), ("1稼働あたりの平均件数", ""),
               ("1稼働あたりの平均金額", "円"), ("1決済あたりの平均金額", "円"), ("目標進捗", "%")]
    return [{"index": str(i), "label": label, "unit": unit} for i, (label, unit) in enumerate(fields)]


def _values(group, department_code):
    data = list(group["entries"].values())
    total = {field: sum(e[field] for e in data) for field in
             ("support_amount", "result_count", "approach_count", "communication_count", "cs_count", "refugee_count")}
    days = len({e["entry_date"] for e in data})
    workers = len(data)
    count = _count_value(department_code, total)
    amount, ap, cm = total["support_amount"], total["approach_count"], total["communication_count"]
    values = [len(group["periods"]), amount, count]
    if department_code == "WV":
        values += [total["cs_count"], total["refugee_count"]]
    return values + [ap, cm, days, workers, len({e["member_id"] for e in data}),
                     amount / workers, _percentage(count, cm), _percentage(cm, ap),
                     _safe_average(ap, workers), _safe_average(cm, workers), _safe_average(count, days),
                     _safe_average(amount, days), _safe_average(amount, count), _percentage(amount, group["target"])]


def build_period_comparison(*, department, reference_date, months=6, metric_index=1):
    end = min(reference_date, timezone.localdate() - timedelta(days=1))
    index = reference_date.year * 12 + reference_date.month - months
    start = reference_date.replace(year=index // 12, month=index % 12 + 1, day=1)
    periods = list(Period.objects.filter(
        month__gte=start, month__lte=reference_date.replace(day=1), end_date__lte=end,
    ).exclude(status="planned").order_by("month", "start_date", "id"))
    metrics = comparison_metrics(department.code)
    labels = [f"{(index + offset) // 12:04d}/{(index + offset) % 12 + 1:02d}" for offset in range(months)]
    result = {"months": months, "start": start, "end": end, "columns": [], "rows": [], "metrics": metrics,
              "chart": {"labels": labels, "datasets": [], **metrics[metric_index]}}
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
    for period in periods:
        route_entries = []
        day = period.start_date
        while day <= period.end_date:
            route_entries.extend(by_day.get(day, []))
            day += timedelta(days=1)
        if not route_entries:
            continue
        key, label = _route_key(period.name)
        group = groups.setdefault(key, {"label": label, "entries": {}, "periods": [], "target": 0, "monthly": {}})
        monthly = group["monthly"].setdefault(f"{period.month:%Y/%m}", {"entries": {}, "periods": [], "target": 0})
        for bucket in (group, monthly):
            bucket["entries"].update({(e["entry_date"], e["member_id"]): e for e in route_entries})
            bucket["periods"].append(f"{period.month:%Y/%m} {period.name}")
            bucket["target"] += targets.get(period.pk, 0)
    for key in sorted(groups):
        group = groups[key]
        values = [_format_number(value, metric["unit"]) for value, metric in zip(_values(group, department.code), metrics)]
        result["columns"].append({"label": group["label"], "periods": group["periods"], "values": values})
        result["chart"]["datasets"].append({
            "label": group["label"],
            "data": [_values(group["monthly"][month], department.code)[metric_index]
                     if month in group["monthly"] else None for month in labels],
        })
    result["rows"] = [{"label": metric["label"], "values": [c["values"][i] for c in result["columns"]]}
                      for i, metric in enumerate(metrics)]
    return result
