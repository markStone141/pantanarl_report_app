from datetime import date

from django.test import TestCase

from apps.accounts.models import Department, Member

from .models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction


class DairymetricsTransactionModelTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(code="UN", name="UN")
        self.member = Member.objects.create(name="Alice", default_department=self.department)

    def test_entry_recalculate_from_transactions_updates_count_and_amount(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 14),
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=1000,
            age_band=MemberMetricTransaction.AGE_BAND_TEENS,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=2000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_OVERSEAS,
        )

        result_count, support_amount = entry.recalculate_from_transactions()
        entry.refresh_from_db()

        self.assertEqual(result_count, 2)
        self.assertEqual(support_amount, 3000)
        self.assertEqual(entry.result_count, 2)
        self.assertEqual(entry.support_amount, 3000)

    def test_department_summary_recalculate_from_entries_updates_totals(self):
        other_member = Member.objects.create(name="Bob", default_department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 14),
            approach_count=8,
            communication_count=4,
            result_count=2,
            support_amount=3000,
        )
        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=date(2026, 5, 14),
            approach_count=6,
            communication_count=3,
            result_count=1,
            support_amount=1500,
        )
        summary = DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=date(2026, 5, 14),
        )

        result_count, support_amount = summary.recalculate_from_entries()
        summary.refresh_from_db()

        self.assertEqual(result_count, 3)
        self.assertEqual(support_amount, 4500)
        self.assertEqual(summary.approach_count, 14)
        self.assertEqual(summary.communication_count, 7)
