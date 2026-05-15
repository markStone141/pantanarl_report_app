from datetime import date

from django.test import TestCase

from apps.accounts.models import Department, Member

from .models import MemberDailyMetricEntry, MetricAdjustment
from .services.final_actuals import (
    collect_department_final_actual_totals,
    collect_department_final_actual_totals_by_codes,
    collect_member_final_actual_totals,
)


class DairymetricsFinalActualsServiceTests(TestCase):
    def setUp(self):
        self.un_department = Department.objects.create(code="UN", name="UN")
        self.wv_department = Department.objects.create(code="WV", name="WV")
        self.alice = Member.objects.create(name="Alice", default_department=self.un_department)
        self.bob = Member.objects.create(name="Bob", default_department=self.un_department)
        self.carol = Member.objects.create(name="Carol", default_department=self.wv_department)

    def test_collect_member_final_actual_totals_merges_entry_boxes_and_adjustments(self):
        MemberDailyMetricEntry.objects.create(
            member=self.alice,
            department=self.un_department,
            entry_date=date(2026, 5, 14),
            approach_count=10,
            communication_count=5,
            result_count=2,
            support_amount=3000,
        )
        MetricAdjustment.objects.create(
            member=self.alice,
            department=self.un_department,
            target_date=date(2026, 5, 14),
            approach_count=2,
            communication_count=1,
            result_count=1,
            support_amount=1000,
            return_postal_count=1,
            return_postal_amount=2500,
            return_qr_count=2,
            return_qr_amount=5000,
        )

        totals = collect_member_final_actual_totals(
            self.alice,
            self.un_department,
            date(2026, 5, 14),
            date(2026, 5, 14),
        )

        self.assertEqual(totals["approach_count"], 12)
        self.assertEqual(totals["communication_count"], 6)
        self.assertEqual(totals["result_count"], 3)
        self.assertEqual(totals["support_amount"], 4000)
        self.assertEqual(totals["return_postal_count"], 1)
        self.assertEqual(totals["return_postal_amount"], 2500)
        self.assertEqual(totals["return_qr_count"], 2)
        self.assertEqual(totals["return_qr_amount"], 5000)

    def test_collect_department_final_actual_totals_can_exclude_adjustments(self):
        MemberDailyMetricEntry.objects.create(
            member=self.alice,
            department=self.un_department,
            entry_date=date(2026, 5, 14),
            approach_count=6,
            communication_count=4,
            result_count=1,
            support_amount=2000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.bob,
            department=self.un_department,
            entry_date=date(2026, 5, 14),
            approach_count=7,
            communication_count=3,
            result_count=2,
            support_amount=3500,
        )
        MetricAdjustment.objects.create(
            member=self.alice,
            department=self.un_department,
            target_date=date(2026, 5, 14),
            support_amount=800,
            result_count=1,
        )

        totals = collect_department_final_actual_totals(
            self.un_department,
            date(2026, 5, 14),
            date(2026, 5, 14),
            include_adjustments=False,
        )

        self.assertEqual(totals["approach_count"], 13)
        self.assertEqual(totals["communication_count"], 7)
        self.assertEqual(totals["result_count"], 3)
        self.assertEqual(totals["support_amount"], 5500)
        self.assertEqual(totals["return_postal_count"], 0)
        self.assertEqual(totals["return_qr_count"], 0)

    def test_collect_department_final_actual_totals_by_codes_returns_grouped_totals(self):
        MemberDailyMetricEntry.objects.create(
            member=self.alice,
            department=self.un_department,
            entry_date=date(2026, 5, 14),
            result_count=2,
            support_amount=3000,
        )
        MetricAdjustment.objects.create(
            member=self.bob,
            department=self.un_department,
            target_date=date(2026, 5, 14),
            result_count=1,
            support_amount=1200,
            return_postal_count=1,
            return_postal_amount=900,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.carol,
            department=self.wv_department,
            entry_date=date(2026, 5, 14),
            cs_count=2,
            refugee_count=1,
            support_amount=2500,
        )
        MetricAdjustment.objects.create(
            member=self.carol,
            department=self.wv_department,
            target_date=date(2026, 5, 14),
            cs_count=1,
            refugee_count=2,
            return_qr_count=1,
            return_qr_amount=700,
        )

        totals_by_code = collect_department_final_actual_totals_by_codes(
            target_codes=["UN", "WV", "XX"],
            start_date=date(2026, 5, 14),
            end_date=date(2026, 5, 14),
        )

        self.assertEqual(totals_by_code["UN"]["result_count"], 3)
        self.assertEqual(totals_by_code["UN"]["support_amount"], 4200)
        self.assertEqual(totals_by_code["UN"]["return_postal_count"], 1)
        self.assertEqual(totals_by_code["WV"]["cs_count"], 3)
        self.assertEqual(totals_by_code["WV"]["refugee_count"], 3)
        self.assertEqual(totals_by_code["WV"]["return_qr_count"], 1)
        self.assertEqual(totals_by_code["XX"]["support_amount"], 0)
