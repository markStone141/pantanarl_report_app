import csv
import io
import tempfile
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.urls import reverse

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
