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
from apps.activity_sites.import_service import import_activity_sites
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


class ActivitySiteImportTests(PerformanceTestBase):
    def _write_csv(self, directory, rows):
        path = Path(directory) / "reviewed-sites.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=["canonical_name", "raw_variants", "department_codes", "active"],
            )
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_dry_run_rolls_back_master_and_history_links(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 8, 2),
            location_name="渋谷 駅前",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, [{
                "canonical_name": "渋谷駅前",
                "raw_variants": "渋谷 駅前",
                "department_codes": "UN",
                "active": "1",
            }])
            result = import_activity_sites(path, dry_run=True)

        entry.refresh_from_db()
        self.assertTrue(result.dry_run)
        self.assertEqual(result.linked_counts["entries"], 1)
        self.assertFalse(ActivitySite.objects.exists())
        self.assertIsNone(entry.activity_site_id)

    def test_apply_is_idempotent_preserves_raw_text_and_inherits_parent_site(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 8, 3),
            location_name="渋谷 駅前",
        )
        metric_transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=1000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, [{
                "canonical_name": "渋谷駅前",
                "raw_variants": "渋谷 駅前",
                "department_codes": "UN",
                "active": "1",
            }])
            first = import_activity_sites(path)
            second = import_activity_sites(path)

        entry.refresh_from_db()
        metric_transaction.refresh_from_db()
        site = ActivitySite.objects.get()
        self.assertEqual(first.linked_counts["entries"], 1)
        self.assertEqual(second.linked_counts["entries"], 0)
        self.assertEqual(ActivitySite.objects.count(), 1)
        self.assertEqual(ActivitySiteAlias.objects.count(), 1)
        self.assertEqual(entry.activity_site_id, site.id)
        self.assertEqual(metric_transaction.activity_site_id, site.id)
        self.assertEqual(entry.location_name, "渋谷 駅前")
        self.assertTrue(site.departments.filter(pk=self.department.pk).exists())

    def test_ambiguous_alias_rejects_entire_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, [
                {"canonical_name": "A現場", "raw_variants": "共通名", "department_codes": "UN", "active": "1"},
                {"canonical_name": "B現場", "raw_variants": "共通名", "department_codes": "UN", "active": "1"},
            ])

            with self.assertRaises(ValidationError):
                import_activity_sites(path)

        self.assertFalse(ActivitySite.objects.exists())

    def test_management_command_dry_run_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, [{
                "canonical_name": "東京駅前",
                "raw_variants": "東京 駅前",
                "department_codes": "UN",
                "active": "1",
            }])
            output = io.StringIO()

            call_command("import_activity_sites", str(path), dry_run=True, stdout=output)

        self.assertIn("DRY RUN: sites=1", output.getvalue())
        self.assertFalse(ActivitySite.objects.exists())


class ActivitySiteProposalManagementTests(PerformanceTestBase):
    def _proposal_with_history(self, name="新宿 南口"):
        proposal = ActivitySiteProposal.objects.create(
            proposed_name=name,
            department=self.department,
            proposed_by=self.user,
        )
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 8, 5 + ActivitySiteProposal.objects.count()),
            location_name=name,
            activity_site_proposal=proposal,
        )
        metric_transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=1000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location=name,
        )
        return proposal, entry, metric_transaction

    def test_dashboard_notifies_admin_and_management_page_is_staff_only(self):
        proposal, _, _ = self._proposal_with_history()

        dashboard_response = self.client.get(reverse("performance_index"))
        manage_response = self.client.get(reverse("performance_activity_site_proposals"))

        self.assertContains(dashboard_response, "新規現場申請を確認 (1)")
        self.assertContains(manage_response, proposal.proposed_name)
        self.assertContains(manage_response, "この名称で承認")

        self.client.logout()
        report_user = self.create_user("proposal-report-user", is_staff=False)
        self.login(report_user)
        denied_response = self.client.get(reverse("performance_activity_site_proposals"))
        self.assertEqual(denied_response.status_code, 403)

    def test_corrected_approval_links_history_and_preserves_raw_text(self):
        proposal, entry, metric_transaction = self._proposal_with_history()

        response = self.client.post(
            reverse("performance_activity_site_proposals"),
            {"proposal_id": proposal.id, "action": "approve", "canonical_name": "新宿南口"},
        )

        self.assertEqual(response.status_code, 302)
        proposal.refresh_from_db()
        entry.refresh_from_db()
        metric_transaction.refresh_from_db()
        site = ActivitySite.objects.get(canonical_name="新宿南口")
        self.assertEqual(proposal.status, ActivitySiteProposal.STATUS_APPROVED)
        self.assertEqual(proposal.resolved_site_id, site.id)
        self.assertEqual(entry.activity_site_id, site.id)
        self.assertEqual(metric_transaction.activity_site_id, site.id)
        self.assertEqual(entry.location_name, "新宿 南口")
        self.assertTrue(ActivitySiteAlias.objects.filter(site=site, normalized_name="新宿 南口").exists())
        self.assertTrue(site.departments.filter(pk=self.department.pk).exists())

        self.member.user = self.user
        self.member.save(update_fields=["user"])
        display_response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry.entry_date.strftime("%Y-%m-%d")},
        )
        self.assertEqual(display_response.context["current_location_name"], site.canonical_name)

        second_response = self.client.post(
            reverse("performance_activity_site_proposals"),
            {"proposal_id": proposal.id, "action": "approve", "canonical_name": "新宿南口"},
        )
        self.assertIn("already-reviewed", second_response.url)
        self.assertEqual(ActivitySite.objects.count(), 1)

    def test_merge_uses_existing_site_and_reject_preserves_history(self):
        existing_site = ActivitySite.objects.create(canonical_name="池袋西口")
        merge_proposal, merge_entry, _ = self._proposal_with_history("池袋 西口")

        merge_response = self.client.post(
            reverse("performance_activity_site_proposals"),
            {"proposal_id": merge_proposal.id, "action": "merge", "resolved_site": existing_site.id},
        )

        self.assertEqual(merge_response.status_code, 302)
        merge_proposal.refresh_from_db()
        merge_entry.refresh_from_db()
        self.assertEqual(merge_proposal.status, ActivitySiteProposal.STATUS_MERGED)
        self.assertEqual(merge_entry.activity_site_id, existing_site.id)

        reject_proposal, reject_entry, _ = self._proposal_with_history("上野新規")
        reject_response = self.client.post(
            reverse("performance_activity_site_proposals"),
            {"proposal_id": reject_proposal.id, "action": "reject", "review_note": "対象外"},
        )
        self.assertEqual(reject_response.status_code, 302)
        reject_proposal.refresh_from_db()
        reject_entry.refresh_from_db()
        self.assertEqual(reject_proposal.status, ActivitySiteProposal.STATUS_REJECTED)
        self.assertEqual(reject_proposal.review_note, "対象外")
        self.assertIsNone(reject_entry.activity_site_id)
        self.assertEqual(reject_entry.location_name, "上野新規")
