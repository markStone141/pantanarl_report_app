from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member, MemberDepartment
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction, MetricAdjustment


User = get_user_model()


class PerformanceManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="perf-admin", password="pass1234", is_staff=True)
        self.client.force_login(self.user)
        self.department = Department.objects.create(code="UN", name="UN")
        self.member = Member.objects.create(name="Alice", default_department=self.department)
        MemberDepartment.objects.create(member=self.member, department=self.department)

    def test_performance_index_renders_final_actual_rows_with_adjustment_totals(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
            result_count=2,
            support_amount=3000,
            approach_count=8,
            communication_count=4,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=entry.entry_date,
            result_count=1,
            support_amount=700,
            return_postal_count=1,
            return_postal_amount=600,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "実績管理")
        self.assertContains(response, "4件")
        self.assertContains(response, "4,300円")
        self.assertContains(response, "戻り 郵送 1 / QR 0")

    def test_performance_entry_edit_updates_daily_entry_and_department_summary(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
            result_count=1,
            support_amount=2000,
            approach_count=5,
            communication_count=2,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=5,
            communication_count=2,
            result_count=1,
            support_amount=2000,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.post(
            reverse("performance_entry_edit", args=[entry.id]),
            {
                "department": self.department.id,
                "entry_date": "2026-05-15",
                "approach_count": 9,
                "communication_count": 6,
                "result_count": 3,
                "support_amount": 4500,
                "daily_target_count": 0,
                "daily_target_amount": 0,
                "location_name": "",
                "memo": "",
            },
        )

        self.assertRedirects(response, reverse("performance_index") + "?updated=entry")
        entry.refresh_from_db()
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry.entry_date)
        self.assertEqual(entry.approach_count, 9)
        self.assertEqual(entry.communication_count, 6)
        self.assertEqual(entry.result_count, 3)
        self.assertEqual(entry.support_amount, 4500)
        self.assertEqual(summary.approach_count, 9)
        self.assertEqual(summary.communication_count, 6)
        self.assertEqual(summary.result_count, 3)
        self.assertEqual(summary.support_amount, 4500)

    def test_performance_entry_edit_locks_amount_when_transactions_exist(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
        )

        response = self.client.get(reverse("performance_entry_edit", args=[entry.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "自動計算されます。")
        self.assertContains(response, "disabled")

    def test_performance_adjustment_create_sets_creator(self):
        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "member": self.member.id,
                "department": self.department.id,
                "target_date": "2026-05-14",
                "source_type": MetricAdjustment.SOURCE_OTHER,
                "approach_count": 0,
                "communication_count": 0,
                "result_count": 1,
                "support_amount": 1200,
                "return_postal_count": 0,
                "return_postal_amount": 0,
                "return_qr_count": 0,
                "return_qr_amount": 0,
                "cs_count": 0,
                "refugee_count": 0,
                "note": "後追い登録",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 14))
        self.assertEqual(adjustment.created_by, self.user)
