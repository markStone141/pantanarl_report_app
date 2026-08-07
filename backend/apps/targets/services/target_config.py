from __future__ import annotations

import re
from datetime import date

from django.utils import timezone

from apps.targets.models import (
    Period,
    TARGET_STATUS_ACTIVE,
    TARGET_STATUS_CHOICES,
    TARGET_STATUS_FINISHED,
    TARGET_STATUS_PLANNED,
)

TARGET_DEPARTMENTS = [
    ("UN", "UN"),
    ("WV", "WV"),
    ("STYLE1", "Style1"),
    ("STYLE2", "Style2"),
]

DEFAULT_METRICS_BY_DEPT = {
    "UN": [("count", "件数", "件"), ("amount", "金額", "円")],
    "WV": [("cs_count", "CS件数", "件"), ("refugee_count", "難民支援件数", "件")],
    "STYLE1": [("amount", "金額", "円")],
    "STYLE2": [("amount", "金額", "円")],
}

PERIOD_SEQUENCE_OPTIONS = list(range(1, 6))
STATUS_OPTIONS = [{"value": value, "label": value} for value, _ in TARGET_STATUS_CHOICES]
STATUS_LABELS = {
    TARGET_STATUS_ACTIVE: "進行中",
    TARGET_STATUS_PLANNED: "予定",
    TARGET_STATUS_FINISHED: "終了",
}
HISTORY_SORT_OPTIONS = [
    {"value": "newest", "label": "新しい順"},
    {"value": "oldest", "label": "古い順"},
    {"value": "status", "label": "状態順"},
]
STATUS_FILTER_OPTIONS = [
    {"value": "", "label": "すべて"},
    {"value": TARGET_STATUS_ACTIVE, "label": STATUS_LABELS[TARGET_STATUS_ACTIVE]},
    {"value": TARGET_STATUS_PLANNED, "label": STATUS_LABELS[TARGET_STATUS_PLANNED]},
    {"value": TARGET_STATUS_FINISHED, "label": STATUS_LABELS[TARGET_STATUS_FINISHED]},
]


def month_status(target_month: date, today: date | None = None) -> str:
    base = today or timezone.localdate()
    current_month = base.replace(day=1)
    if target_month == current_month:
        return TARGET_STATUS_ACTIVE
    if target_month > current_month:
        return TARGET_STATUS_PLANNED
    return TARGET_STATUS_FINISHED


def period_status(start_date: date, end_date: date, today: date | None = None) -> str:
    base = today or timezone.localdate()
    if start_date <= base <= end_date:
        return TARGET_STATUS_ACTIVE
    if base < start_date:
        return TARGET_STATUS_PLANNED
    return TARGET_STATUS_FINISHED


def stored_period_status(period: Period | None) -> str:
    if not period:
        return TARGET_STATUS_PLANNED
    return period.status


def period_name(*, month: date, sequence: int) -> str:
    return f"{month.year}年度{month.month}月 第{sequence}次路程"


def period_label(period: Period | None) -> str:
    if not period:
        return "未設定"
    return f"{period.name} ({period.start_date:%m/%d} - {period.end_date:%m/%d})"


def sequence_from_period_name(name: str) -> int:
    match = re.search(r"第(\d+)次路程", name)
    if not match:
        return 1
    return int(match.group(1))
