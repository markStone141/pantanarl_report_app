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
        self.assertContains(response, "直近稼働の全体実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, "日目達成率")
        self.assertContains(response, entry.entry_date.strftime("%m/%d"))
        self.assertContains(response, "補正実績入力")
        self.assertContains(response, reverse("performance_adjustments"))

    def test_performance_member_dashboard_redirects_to_performance_login(self):
        self.client.logout()

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('performance_login')}?next={reverse('performance_member_dashboard')}",
        )

    def test_performance_index_defaults_dashboard_department_to_un(self):
        other_department = Department.objects.create(code="WV", name="WV", is_active=True)
        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].code, "UN")
        self.assertContains(response, "月目標達成率")

    def test_performance_index_can_switch_dashboard_department(self):
        other_department = Department.objects.create(code="WV", name="WV", is_active=True)

        response = self.client.get(reverse("performance_index"), {"dashboard_department": other_department.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].id, other_department.id)
        self.assertContains(
            response,
            f'<option value="{other_department.id}" selected>WV</option>',
            html=True,
        )

    def test_performance_login_redirects_member_to_member_dashboard(self):
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-login", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])

        response = self.client.post(
            reverse("performance_login"),
            {"login_id": "perf-member-login", "password": "pass1234"},
        )

        self.assertRedirects(response, reverse("performance_member_dashboard"))

    def test_performance_login_redirects_admin_to_admin_dashboard(self):
        self.client.logout()

        response = self.client.post(
            reverse("performance_login"),
            {"login_id": "perf-admin", "password": "pass1234"},
        )

        self.assertRedirects(response, reverse("performance_index"))

    def test_performance_history_uses_selected_month_and_period_for_progress_cards(self):
        today = timezone.localdate()
        selected_month = date(today.year, 4, 1)
        selected_period = Period.objects.create(
            month=selected_month,
            name="4月第2次路程",
            status="closed",
            start_date=selected_month,
            end_date=selected_month + timedelta(days=6),
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
            target_month=selected_month,
            metric=amount_metric,
            value=12000,
        )
        PeriodTargetMetricValue.objects.create(
            period=selected_period,
            department=self.department,
            metric=amount_metric,
            value=28000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_month + timedelta(days=1),
            result_count=1,
            support_amount=4500,
        )

        response = self.client.get(
            reverse("performance_history"),
            {
                "dashboard_scope": "period",
                "dashboard_department": str(self.department.id),
                "dashboard_month": selected_month.strftime("%Y-%m"),
                "dashboard_period": str(selected_period.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4月第2次路程")
        self.assertContains(response, "28,000円")
        self.assertContains(response, "実績閲覧")

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
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-14",
                "source_type": MetricAdjustment.SOURCE_QR,
                "location_name": "渋谷駅前",
                "amount_choice": "1500",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 14))
        self.assertEqual(adjustment.created_by, self.user)
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_QR)
        self.assertEqual(adjustment.return_qr_count, 1)
        self.assertEqual(adjustment.return_qr_amount, 1500)
        self.assertEqual(adjustment.location_name, "渋谷駅前")
        self.assertEqual(adjustment.support_amount, 0)

    def test_performance_adjustment_create_increase_counts_as_one(self):
        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-15",
                "source_type": MetricAdjustment.SOURCE_INCREASE,
                "location_name": "池袋駅前",
                "amount_choice": "direct",
                "amount": "6200",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 15))
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_INCREASE)
        self.assertEqual(adjustment.result_count, 1)
        self.assertEqual(adjustment.support_amount, 6200)
        self.assertEqual(adjustment.location_name, "池袋駅前")

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
        self.assertContains(response, "目標達成率")
        self.assertContains(response, "70.0%")
        self.assertContains(response, "7,000円")
        self.assertContains(response, "補正 2,000円")
        self.assertContains(response, "通常実績")
        self.assertContains(response, "補正実績")
        self.assertContains(response, "残り")
        self.assertContains(response, 'data-chart-values="5000,2000,3000"', html=False)

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
        self.assertContains(response, "今月累計")
        self.assertContains(response, "路程累計")
        self.assertContains(response, "直近の実績")
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

    def test_performance_index_marks_member_when_last_three_entries_are_zero_count(self):
        today = timezone.localdate()
        for offset in range(3):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=0,
                support_amount=0,
                activity_closed=True,
            )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3稼働連続0件")

    def test_performance_index_marks_member_when_last_three_entries_have_results(self):
        today = timezone.localdate()
        for offset, count in enumerate((2, 1, 3)):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=count,
                support_amount=1000 * count,
                activity_closed=True,
            )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3稼働連続1件以上")

    def test_performance_member_detail_shows_realtime_dashboard(self):
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
            source_type=MetricAdjustment.SOURCE_POSTAL,
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
        self.assertContains(response, "直近稼働の実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, "-10")
        self.assertContains(response, "+10")
        self.assertContains(response, "日目達成率")
        self.assertContains(response, "AP/CM")
        self.assertContains(response, entry_today.entry_date.strftime("%m/%d"))
        self.assertContains(response, "全体の月目標")
        self.assertContains(response, "全体の路程目標")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "個人の路程目標")
        self.assertContains(response, "Aliceさんの割合")
        self.assertContains(response, "9,400円 / 9,400円")
        self.assertContains(response, "月目標")
        self.assertContains(response, "修正")
        self.assertContains(response, "直近30日の実績")
        self.assertContains(response, "直近30日の補正実績")

    def test_performance_member_history_shows_scoped_entries_and_adjustments(self):
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
            source_type=MetricAdjustment.SOURCE_POSTAL,
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

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績閲覧")
        self.assertContains(response, "集計条件")
        self.assertContains(response, "全体の月目標")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "日次実績")
        self.assertContains(response, "補正実績")
        self.assertContains(response, entry_today.entry_date.strftime("%Y/%m/%d"))
        self.assertContains(response, "郵送")
        self.assertContains(response, "戻り 郵送 1 / QR 0")
        self.assertContains(response, "900円")
        self.assertContains(response, "初回決済")
        self.assertNotContains(response, "<th>メモ</th>", html=False)

    def test_performance_member_history_shows_qr_adjustment_amount_and_count(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
        )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QR")
        self.assertContains(response, "1件")
        self.assertContains(response, "1500円")
        self.assertContains(response, "補正実績")

    def test_performance_member_detail_shows_target_forms_when_edit_requested(self):
        today = timezone.localdate()
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )

        response = self.client.get(
            reverse("performance_member_detail", args=[self.member.id, self.department.id]),
            {"month": today.strftime("%Y-%m"), "edit_month_target": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月目標を保存")

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
        self.assertContains(response, "直近30日の実績")
        self.assertContains(response, "直近30日の補正実績")
        self.assertContains(response, reverse("performance_member_history"))
        self.assertContains(response, "実績管理ダッシュボード")
        self.assertContains(response, "決済入力")
        self.assertContains(response, "実績閲覧")
        self.assertContains(response, "Metrics V2")
        self.assertNotContains(response, "総合管理者ページ")

    def test_performance_member_history_uses_logged_in_member_profile(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-history", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=1,
            support_amount=3000,
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績閲覧")
        self.assertContains(response, "集計条件")
        self.assertContains(response, "実績管理ダッシュボード")
        self.assertContains(response, "決済入力")
        self.assertContains(response, "Metrics V2")

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
