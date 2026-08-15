import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, TextIO

from apps.dairymetrics.models import (
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MetricAdjustment,
    WVMetricCancellation,
)
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine


_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass
class ActivitySiteDiscoveryRow:
    normalized_name: str
    suggested_canonical_name: str
    raw_variants: set[str] = field(default_factory=set)
    source_types: set[str] = field(default_factory=set)
    department_codes: set[str] = field(default_factory=set)
    record_count: int = 0
    first_activity_date: date | None = None
    latest_activity_date: date | None = None

    def add(self, *, raw_name: str, source_type: str, department_code: str, activity_date: date) -> None:
        self.raw_variants.add(raw_name)
        self.source_types.add(source_type)
        if department_code:
            self.department_codes.add(department_code)
        self.record_count += 1
        if self.first_activity_date is None or activity_date < self.first_activity_date:
            self.first_activity_date = activity_date
        if self.latest_activity_date is None or activity_date > self.latest_activity_date:
            self.latest_activity_date = activity_date


def normalize_activity_site_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized).strip()
    return normalized.casefold()


def _clean_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return _WHITESPACE_PATTERN.sub(" ", normalized).strip()


def _site_occurrence_querysets() -> Iterable[tuple[str, Iterable[tuple[str, date, str]]]]:
    yield "daily_entry", MemberDailyMetricEntry.objects.exclude(location_name="").values_list(
        "location_name", "entry_date", "department__code"
    )
    yield "transaction", MemberMetricTransaction.objects.exclude(location="").values_list(
        "location", "entry__entry_date", "entry__department__code"
    )
    yield "adjustment", MetricAdjustment.objects.exclude(location_name="").values_list(
        "location_name", "target_date", "department__code"
    )
    yield "cancellation", WVMetricCancellation.objects.exclude(location_name="").values_list(
        "location_name", "target_date", "department__code"
    )
    yield "daily_report", DailyDepartmentReport.objects.exclude(location="").values_list(
        "location", "report_date", "department__code"
    )
    yield "daily_report_line", DailyDepartmentReportLine.objects.exclude(location="").values_list(
        "location", "report__report_date", "report__department__code"
    )


def collect_activity_site_discovery_rows() -> list[ActivitySiteDiscoveryRow]:
    rows_by_name: dict[str, ActivitySiteDiscoveryRow] = {}
    for source_type, occurrences in _site_occurrence_querysets():
        for raw_name, activity_date, department_code in occurrences.iterator(chunk_size=2000):
            display_name = _clean_display_name(raw_name)
            normalized_name = normalize_activity_site_name(display_name)
            if not normalized_name:
                continue
            row = rows_by_name.setdefault(
                normalized_name,
                ActivitySiteDiscoveryRow(
                    normalized_name=normalized_name,
                    suggested_canonical_name=display_name,
                ),
            )
            row.add(
                raw_name=str(raw_name).strip(),
                source_type=source_type,
                department_code=department_code,
                activity_date=activity_date,
            )
    return sorted(rows_by_name.values(), key=lambda row: row.normalized_name)


def write_activity_site_discovery_csv(output: TextIO, rows: Iterable[ActivitySiteDiscoveryRow]) -> None:
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "normalized_name",
            "suggested_canonical_name",
            "raw_variants",
            "source_types",
            "record_count",
            "first_activity_date",
            "latest_activity_date",
            "department_codes",
            "canonical_name",
            "active",
            "notes",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.normalized_name,
                row.suggested_canonical_name,
                " | ".join(sorted(row.raw_variants)),
                " | ".join(sorted(row.source_types)),
                row.record_count,
                row.first_activity_date.isoformat() if row.first_activity_date else "",
                row.latest_activity_date.isoformat() if row.latest_activity_date else "",
                " | ".join(sorted(row.department_codes)),
                "",
                "1",
                "",
            ]
        )
