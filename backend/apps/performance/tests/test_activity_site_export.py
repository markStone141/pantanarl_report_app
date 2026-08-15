import csv
import io
import tempfile
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from apps.activity_sites.models import ActivitySite, ActivitySiteAlias, ActivitySiteProposal
from apps.dairymetrics.models import (
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MetricAdjustment,
    WVMetricCancellation,
)
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine
from .base import PerformanceTestBase


class ActivitySiteExportTests(PerformanceTestBase):
    def _create_historical_sites(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 7, 1),
            location_name="  渋谷　駅前  ",
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=1000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷 駅前",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 7, 3),
            location_name="新宿西口",
        )
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)
        WVMetricCancellation.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=date(2026, 7, 4),
            location_name="新宿西口",
        )
        report = DailyDepartmentReport.objects.create(
            department=self.department,
            report_date=date(2026, 6, 29),
            location="渋谷 駅前",
        )
        DailyDepartmentReportLine.objects.create(
            report=report,
            member=self.member,
            location="   ",
        )

    def _response_rows(self):
        response = self.client.get(reverse("performance_activity_sites_export"))
        content = response.content.decode("utf-8-sig")
        return response, list(csv.DictReader(io.StringIO(content)))

    def test_export_deduplicates_normalized_names_and_includes_source_metadata(self):
        self._create_historical_sites()

        response, rows = self._response_rows()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(rows), 2)
        shibuya = next(row for row in rows if row["normalized_name"] == "渋谷 駅前")
        self.assertEqual(shibuya["record_count"], "3")
        self.assertEqual(shibuya["first_activity_date"], "2026-06-29")
        self.assertEqual(shibuya["latest_activity_date"], "2026-07-01")
        self.assertEqual(shibuya["department_codes"], "UN")
        self.assertIn("daily_entry", shibuya["source_types"])
        self.assertIn("daily_report", shibuya["source_types"])
        self.assertIn("transaction", shibuya["source_types"])
        self.assertEqual(shibuya["canonical_name"], "")
        self.assertEqual(shibuya["active"], "1")

    def test_export_is_admin_only_and_button_is_hidden_from_report_user(self):
        self.client.logout()
        report_user = self.create_user("site-report-user", is_staff=False)
        self.create_member(name="Report User", department=self.department, user=report_user)
        self.login(report_user)

        export_response = self.client.get(reverse("performance_activity_sites_export"))
        index_response = self.client.get(reverse("performance_index"))

        self.assertEqual(export_response.status_code, 302)
        self.assertNotContains(index_response, "現場一覧CSVを出力")

    def test_admin_dashboard_shows_export_button(self):
        response = self.client.get(reverse("performance_index"))

        self.assertContains(response, "現場一覧CSVを出力")
        self.assertContains(response, reverse("performance_activity_sites_export"))

    def test_management_command_writes_excel_compatible_csv(self):
        self._create_historical_sites()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "sites.csv"

            call_command("export_activity_sites", output=str(output_path))

            raw = output_path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            self.assertEqual(len(rows), 2)


class ActivitySiteModelTests(PerformanceTestBase):
    def test_site_and_alias_names_are_normalized_for_unique_matching(self):
        site = ActivitySite.objects.create(canonical_name="  Ｓｈｉｂｕｙａ　駅前  ", created_by=self.user)
        alias = ActivitySiteAlias.objects.create(site=site, alias_name="渋谷   駅前")

        self.assertEqual(site.normalized_name, "shibuya 駅前")
        self.assertEqual(alias.normalized_name, "渋谷 駅前")

        with self.assertRaises(IntegrityError), transaction.atomic():
            ActivitySite.objects.create(canonical_name="SHIBUYA 駅前")

    def test_only_one_pending_proposal_is_allowed_per_department_and_name(self):
        ActivitySiteProposal.objects.create(
            proposed_name="新宿　西口",
            department=self.department,
            proposed_by=self.user,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ActivitySiteProposal.objects.create(
                proposed_name="  新宿 西口  ",
                department=self.department,
                proposed_by=self.user,
            )

    def test_alias_cannot_shadow_another_canonical_site_name(self):
        first_site = ActivitySite.objects.create(canonical_name="池袋東口")
        ActivitySite.objects.create(canonical_name="池袋西口")

        with self.assertRaises(ValidationError):
            ActivitySiteAlias.objects.create(site=first_site, alias_name="  池袋西口  ")

    def test_approved_or_merged_proposal_requires_resolved_site(self):
        proposal = ActivitySiteProposal(
            proposed_name="池袋東口",
            department=self.department,
            status=ActivitySiteProposal.STATUS_APPROVED,
        )

        with self.assertRaises(ValidationError):
            proposal.full_clean()

    def test_legacy_location_text_survives_site_deletion(self):
        site = ActivitySite.objects.create(canonical_name="上野駅前")
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 8, 1),
            location_name="上野 駅前",
            activity_site=site,
        )
        adjustment = MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 8, 1),
            location_name="上野 駅前",
            activity_site=site,
        )
        metric_transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=1000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="上野 駅前",
            activity_site=site,
        )
        report = DailyDepartmentReport.objects.create(
            department=self.department,
            report_date=date(2026, 8, 1),
            location="上野 駅前",
            activity_site=site,
        )
        report_line = DailyDepartmentReportLine.objects.create(
            report=report,
            member=self.member,
            location="上野 駅前",
            activity_site=site,
        )
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Site Member", department=wv_department)
        cancellation = WVMetricCancellation.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=date(2026, 8, 1),
            location_name="上野 駅前",
            activity_site=site,
        )

        site.delete()
        entry.refresh_from_db()
        adjustment.refresh_from_db()
        metric_transaction.refresh_from_db()
        report.refresh_from_db()
        report_line.refresh_from_db()
        cancellation.refresh_from_db()

        self.assertIsNone(entry.activity_site_id)
        self.assertIsNone(adjustment.activity_site_id)
        self.assertIsNone(metric_transaction.activity_site_id)
        self.assertIsNone(report.activity_site_id)
        self.assertIsNone(report_line.activity_site_id)
        self.assertIsNone(cancellation.activity_site_id)
        self.assertEqual(entry.location_name, "上野 駅前")
        self.assertEqual(adjustment.location_name, "上野 駅前")

    def test_site_resolving_an_approved_proposal_is_protected_from_deletion(self):
        site = ActivitySite.objects.create(canonical_name="品川駅前")
        proposal = ActivitySiteProposal.objects.create(
            proposed_name="品川駅前",
            department=self.department,
            proposed_by=self.user,
            status=ActivitySiteProposal.STATUS_APPROVED,
            resolved_site=site,
        )

        with self.assertRaises(ProtectedError):
            site.delete()

        self.assertTrue(ActivitySiteProposal.objects.filter(pk=proposal.pk).exists())
