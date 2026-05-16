from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.dairymetrics.models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric


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
        self.assertContains(response, "有効メンバー一覧")
        self.assertContains(response, "直近30稼働の全体実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, entry.entry_date.strftime("%m/%d"))

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

    def test_performance_index_shows_activity_lists_and_progress_with_adjustments(self):
        today = timezone.localdate()
        other_member = Member.objects.create(name="Bob", default_department=self.department)
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=5),
        )
        amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=self.department,
            target_month=today.replace(day=1),
            metric=amount_metric,
            value=10000,
        )
        PeriodTargetMetricValue.objects.create(
            period=active_period,
            department=self.department,
            metric=amount_metric,
            value=30000,
        )
        active_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            activity_closed=False,
        )
        finished_entry = MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=2000,
            activity_closed=True,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            support_amount=500,
        )
        MetricAdjustment.objects.create(
            member=other_member,
            department=self.department,
            target_date=today - timedelta(days=1),
            support_amount=1500,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "現在活動中メンバー")
        self.assertContains(response, "活動終了メンバー")
        self.assertContains(response, active_entry.member.name)
        self.assertContains(response, finished_entry.member.name)
        self.assertContains(response, "月目標に対する達成率")
        self.assertContains(response, "路程目標に対する達成率")
        self.assertContains(response, "70.0%")
        self.assertContains(response, "23.3%")
        self.assertContains(response, "7,000円")

    def test_performance_index_shows_active_member_cards_with_detail_link(self):
        today = timezone.localdate()
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        active_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            activity_closed=False,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=2,
            support_amount=2500,
            activity_closed=True,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            support_amount=500,
        )
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有効メンバー一覧")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "今月の実績")
        self.assertContains(response, "今路程の実績")
        self.assertContains(response, "直近の実績")
        self.assertContains(response, "月目標達成率")
        self.assertContains(response, "路程目標達成率")
        self.assertContains(response, "60.0%")
        self.assertContains(response, "30.0%")
        self.assertContains(response, reverse("performance_member_detail", args=[self.member.id, self.department.id]))

    def test_performance_index_shows_enabled_member_card_without_today_entry(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=2),
            result_count=2,
            support_amount=2800,
            activity_closed=True,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有効メンバー一覧")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "2,800円")
        self.assertContains(response, reverse("performance_member_detail", args=[self.member.id, self.department.id]))

    def test_performance_index_orders_enabled_member_cards_by_recent_entry_desc(self):
        today = timezone.localdate()
        newer_member = Member.objects.create(name="Newer", default_department=self.department)
        older_member = Member.objects.create(name="Older", default_department=self.department)
        MemberDepartment.objects.create(member=newer_member, department=self.department)
        MemberDepartment.objects.create(member=older_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=older_member,
            department=self.department,
            entry_date=today - timedelta(days=3),
            support_amount=1000,
        )
        MemberDailyMetricEntry.objects.create(
            member=newer_member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            support_amount=2000,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertLess(content.index("Newer"), content.index("Older"))

    def test_performance_member_detail_shows_current_month_entries(self):
        today = timezone.localdate()
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        entry_today = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            approach_count=8,
            communication_count=4,
        )
        entry_old = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=2,
            support_amount=2500,
            approach_count=6,
            communication_count=3,
        )
        MemberMetricTransaction.objects.create(
            entry=entry_today,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            return_postal_count=1,
            return_postal_amount=900,
        )
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績ダッシュボード")
        self.assertContains(response, "直近30稼働の実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, "-10")
        self.assertContains(response, "+10")
        self.assertContains(response, entry_today.entry_date.strftime("%m/%d"))
        self.assertContains(response, "全体の月目標")
        self.assertContains(response, "全体の路程目標")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "個人の路程目標")
        self.assertContains(response, entry_today.entry_date.strftime("%Y/%m/%d"))
        self.assertContains(response, entry_old.entry_date.strftime("%Y/%m/%d"))
        self.assertContains(response, "決済一覧")
        self.assertContains(response, "初回決済")
        self.assertContains(response, "渋谷")
        self.assertContains(response, "月目標を保存")
        self.assertContains(response, "路程目標を保存")
        self.assertContains(response, "補正実績")
        self.assertContains(response, "戻り 郵送 1 / QR 0")
        self.assertContains(response, "編集")

    def test_performance_member_dashboard_uses_logged_in_member_profile(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=timezone.localdate().replace(day=1),
            target_amount=9000,
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績ダッシュボード")
        self.assertContains(response, "個人の月目標")

    def test_performance_member_detail_can_save_month_target(self):
        today = timezone.localdate()

        response = self.client.post(
            f"{reverse('performance_member_detail', args=[self.member.id, self.department.id])}?month={today:%Y-%m}",
            {
                "action": "save_month_target",
                "department": self.department.id,
                "target_count": 3,
                "target_amount": 12000,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_member_detail', args=[self.member.id, self.department.id])}?month={today:%Y-%m}&saved=target",
        )
        target = MemberMonthMetricTarget.objects.get(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
        )
        self.assertEqual(target.target_count, 3)
        self.assertEqual(target.target_amount, 12000)
