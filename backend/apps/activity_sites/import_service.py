import csv
from dataclasses import dataclass, field
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import Department
from apps.dairymetrics.models import (
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MetricAdjustment,
    WVMetricCancellation,
)
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine
from .models import ActivitySite, ActivitySiteAlias, ActivitySiteDepartment, normalize_site_name


@dataclass
class SiteImportRow:
    canonical_name: str
    is_active: bool = True
    aliases: set[str] = field(default_factory=set)
    department_codes: set[str] = field(default_factory=set)


@dataclass
class SiteImportResult:
    site_count: int = 0
    alias_count: int = 0
    linked_counts: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False


def _split_values(value: str) -> set[str]:
    return {part.strip() for part in str(value or "").split("|") if part.strip()}


def _parse_active(value: str) -> bool:
    return str(value or "1").strip().casefold() not in {"0", "false", "no", "inactive", "無効"}


def _load_rows(csv_path: Path) -> dict[str, SiteImportRow]:
    grouped: dict[str, SiteImportRow] = {}
    alias_owners: dict[str, str] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        for line_number, raw in enumerate(csv.DictReader(source), start=2):
            canonical_name = str(raw.get("canonical_name") or "").strip()
            if not canonical_name:
                raise ValidationError(f"{line_number}行目: canonical_name を入力してください。")
            canonical_key = normalize_site_name(canonical_name)
            row = grouped.setdefault(
                canonical_key,
                SiteImportRow(canonical_name=canonical_name, is_active=_parse_active(raw.get("active"))),
            )
            row.aliases.update(_split_values(raw.get("raw_variants")))
            row.department_codes.update(_split_values(raw.get("department_codes")))
            for alias_name in row.aliases | {canonical_name}:
                alias_key = normalize_site_name(alias_name)
                owner = alias_owners.setdefault(alias_key, canonical_key)
                if owner != canonical_key:
                    raise ValidationError(f"{line_number}行目: '{alias_name}' が複数の現場に割り当てられています。")
    if not grouped:
        raise ValidationError("取込対象の現場がありません。")
    return grouped


def _import_master_rows(rows: dict[str, SiteImportRow]) -> tuple[int, int]:
    requested_codes = {code for row in rows.values() for code in row.department_codes}
    departments = {department.code: department for department in Department.objects.filter(code__in=requested_codes)}
    missing_codes = sorted(requested_codes - departments.keys())
    if missing_codes:
        raise ValidationError(f"存在しない部署コードです: {', '.join(missing_codes)}")

    sites: dict[str, ActivitySite] = {}
    for canonical_key, row in rows.items():
        site = ActivitySite.objects.filter(normalized_name=canonical_key).first()
        if site is None:
            site = ActivitySite(canonical_name=row.canonical_name, is_active=row.is_active)
        else:
            site.canonical_name = row.canonical_name
            site.is_active = row.is_active
        site.save()
        sites[canonical_key] = site
        ActivitySiteDepartment.objects.filter(site=site).delete()
        ActivitySiteDepartment.objects.bulk_create(
            [ActivitySiteDepartment(site=site, department=departments[code]) for code in sorted(row.department_codes)]
        )

    alias_count = 0
    for canonical_key, row in rows.items():
        site = sites[canonical_key]
        for alias_name in sorted(row.aliases):
            alias_key = normalize_site_name(alias_name)
            if not alias_key or alias_key == site.normalized_name:
                continue
            existing = ActivitySiteAlias.objects.filter(normalized_name=alias_key).first()
            if existing and existing.site_id != site.id:
                raise ValidationError(f"'{alias_name}' は別の現場の別名として登録済みです。")
            if existing is None:
                ActivitySiteAlias.objects.create(
                    site=site,
                    alias_name=alias_name,
                    source=ActivitySiteAlias.SOURCE_IMPORT,
                )
            alias_count += 1
    return len(sites), alias_count


def _site_id_map() -> dict[str, int]:
    mapping = dict(ActivitySite.objects.values_list("normalized_name", "id"))
    mapping.update(ActivitySiteAlias.objects.values_list("normalized_name", "site_id"))
    return mapping


def _link_direct(model, text_field: str, mapping: dict[str, int]) -> int:
    updates = []
    queryset = model.objects.filter(activity_site__isnull=True).exclude(**{text_field: ""})
    for record_id, raw_name in queryset.values_list("id", text_field).iterator(chunk_size=2000):
        site_id = mapping.get(normalize_site_name(raw_name))
        if site_id:
            updates.append(model(pk=record_id, activity_site_id=site_id))
    model.objects.bulk_update(updates, ["activity_site"], batch_size=1000)
    return len(updates)


def _inherit_parent_links() -> dict[str, int]:
    transaction_updates = [
        MemberMetricTransaction(pk=record_id, activity_site_id=site_id)
        for record_id, site_id in MemberMetricTransaction.objects.filter(
            activity_site__isnull=True,
            location="",
            entry__activity_site__isnull=False,
        ).values_list("id", "entry__activity_site_id")
    ]
    line_updates = [
        DailyDepartmentReportLine(pk=record_id, activity_site_id=site_id)
        for record_id, site_id in DailyDepartmentReportLine.objects.filter(
            activity_site__isnull=True,
            location="",
            report__activity_site__isnull=False,
        ).values_list("id", "report__activity_site_id")
    ]
    MemberMetricTransaction.objects.bulk_update(transaction_updates, ["activity_site"], batch_size=1000)
    DailyDepartmentReportLine.objects.bulk_update(line_updates, ["activity_site"], batch_size=1000)
    return {"transaction_inherited": len(transaction_updates), "report_line_inherited": len(line_updates)}


def import_activity_sites(csv_path: str | Path, *, dry_run: bool = False, backfill: bool = True) -> SiteImportResult:
    path = Path(csv_path)
    if not path.is_file():
        raise ValidationError(f"CSVが見つかりません: {path}")
    rows = _load_rows(path)
    with transaction.atomic():
        site_count, alias_count = _import_master_rows(rows)
        linked_counts = {}
        if backfill:
            mapping = _site_id_map()
            for label, model, text_field in [
                ("entries", MemberDailyMetricEntry, "location_name"),
                ("transactions", MemberMetricTransaction, "location"),
                ("adjustments", MetricAdjustment, "location_name"),
                ("cancellations", WVMetricCancellation, "location_name"),
                ("reports", DailyDepartmentReport, "location"),
                ("report_lines", DailyDepartmentReportLine, "location"),
            ]:
                linked_counts[label] = _link_direct(model, text_field, mapping)
            linked_counts.update(_inherit_parent_links())
        if dry_run:
            transaction.set_rollback(True)
        return SiteImportResult(site_count, alias_count, linked_counts, dry_run)
