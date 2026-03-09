from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.targets.models import Period

from .forms import MemberDailyMetricEntryForm
from .models import MemberDailyMetricEntry, MetricAdjustment


class DairyMetricsLoginTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="member1", password="pass123")
        self.member = Member.objects.create(name="Member One", user=self.user)
        self.department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=self.department)

    def test_member_can_login(self):
        response = self.client.post(
            reverse("dairymetrics_login"),
            {"login_id": "member1", "password": "pass123"},
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard"))

    def test_non_member_user_is_rejected(self):
        get_user_model().objects.create_user(username="outsider", password="pass123")
        response = self.client.post(
            reverse("dairymetrics_login"),
            {"login_id": "outsider", "password": "pass123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DairyMetrics を利用できるメンバーではありません。")


class DairyMetricsDashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="member2", password="pass123")
        self.member = Member.objects.create(name="Member Two", user=self.user)
        self.department = Department.objects.create(code="WV", name="WV")
        MemberDepartment.objects.create(member=self.member, department=self.department)

    def test_dashboard_aggregates_entries_and_adjustments(self):
        teammate_user = get_user_model().objects.create_user(username="member2b", password="pass123")
        teammate = Member.objects.create(name="Member Teammate", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=10,
            communication_count=6,
            support_amount=4000,
            daily_target_count=5,
            daily_target_amount=8000,
            cs_count=2,
            refugee_count=1,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            support_amount=2000,
            cs_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=date(2026, 3, 8),
            approach_count=4,
            communication_count=3,
            support_amount=1500,
            cs_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "6,000")
        self.assertContains(response, "4")
        self.assertContains(response, "10")
        self.assertContains(response, "過去7日の推移")
        self.assertContains(response, "CS 3 / 難民 1")
        self.assertContains(response, "今日:")
        self.assertContains(response, "今日の目標達成率")
        self.assertContains(response, "80.0%")
        self.assertContains(response, "残り 1")
        self.assertContains(response, "比較を見る")
        self.assertNotContains(response, "今日の順位")
        self.assertContains(response, "今日のアプローチ")
        self.assertContains(response, "今日のコミュニケーション")
        self.assertNotContains(response, "アプローチ 平均/合計")
        self.assertNotContains(response, "今日の自己ベスト")
        self.assertNotContains(response, "伸びた項目")
        self.assertNotContains(response, "落ちた項目")

    def test_comparison_page_shows_ranking_metrics(self):
        teammate_user = get_user_model().objects.create_user(username="member2c", password="pass123")
        teammate = Member.objects.create(name="Member Compare", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=8,
            communication_count=5,
            support_amount=3200,
            cs_count=2,
            refugee_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=5,
            communication_count=2,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_compare"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "今日の順位")
        self.assertContains(response, "チーム平均との差")
        self.assertContains(response, "前期間比")
        self.assertContains(response, "ダッシュボードへ戻る")

    def test_entry_form_updates_existing_record(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=5,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("dairymetrics_entry"),
            {
                "department": self.department.id,
                "entry_date": "2026-03-09",
                "approach_count": 9,
                "communication_count": 4,
                "result_count": 2,
                "support_amount": 3000,
                "cs_count": 1,
                "refugee_count": 1,
                "location_name": "Tokyo",
                "memo": "updated",
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard") + "?saved=1")
        entry.refresh_from_db()
        self.assertEqual(entry.approach_count, 9)
        self.assertEqual(MemberDailyMetricEntry.objects.count(), 1)
        self.assertFalse(entry.activity_closed)

    def test_close_activity_sets_flag(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("dairymetrics_entry"),
            {
                "department": self.department.id,
                "entry_date": "2026-03-09",
                "approach_count": 6,
                "communication_count": 3,
                "support_amount": 2500,
                "daily_target_count": 4,
                "daily_target_amount": 3000,
                "cs_count": 2,
                "refugee_count": 0,
                "submit_action": "close_activity",
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard") + "?saved=1")
        entry = MemberDailyMetricEntry.objects.get()
        self.assertTrue(entry.activity_closed)
        self.assertIsNotNone(entry.activity_closed_at)

    def test_save_turns_off_activity_closed_flag(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=6,
            activity_closed=True,
            activity_closed_at=timezone.now(),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("dairymetrics_entry"),
            {
                "department": self.department.id,
                "entry_date": "2026-03-09",
                "approach_count": 8,
                "communication_count": 2,
                "support_amount": 2000,
                "daily_target_count": 4,
                "daily_target_amount": 2500,
                "cs_count": 1,
                "refugee_count": 1,
                "submit_action": "save",
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard") + "?saved=1")
        entry.refresh_from_db()
        self.assertFalse(entry.activity_closed)
        self.assertIsNone(entry.activity_closed_at)

    def test_dashboard_ajax_switches_department_and_prefills_form(self):
        second_department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=second_department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=second_department,
            entry_date=date(2026, 3, 9),
            approach_count=7,
            communication_count=3,
            result_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("dairymetrics_dashboard"),
            {"department": "UN"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["department_code"], "UN")
        self.assertIn("UN", payload["card_html"])
        self.assertIn('value="7"', payload["form_html"])
        self.assertIn("今日", payload["card_html"])

    def test_dashboard_initial_modal_prefills_existing_entry(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=11,
            communication_count=5,
            support_amount=3500,
            daily_target_count=6,
            daily_target_amount=5000,
            cs_count=2,
            refugee_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="11"')
        self.assertContains(response, 'value="3500"')
        self.assertContains(response, 'value="6"')

    def test_wv_entry_form_hides_result_count_and_uses_japanese_labels(self):
        form = MemberDailyMetricEntryForm(
            member=self.member,
            initial={"department": self.department},
        )
        self.assertIn("cs_count", form.fields)
        self.assertIn("refugee_count", form.fields)
        self.assertNotIn("result_count", form.fields)
        self.assertIn("daily_target_count", form.fields)
        self.assertIn("daily_target_amount", form.fields)
        self.assertEqual(form.fields["approach_count"].label, "アプローチ")
        self.assertEqual(form.fields["support_amount"].label, "支援金額")
        self.assertEqual(form.fields["daily_target_count"].label, "今日の目標 件数")
        self.assertEqual(
            list(form.fields.keys())[:6],
            ["department", "entry_date", "daily_target_count", "daily_target_amount", "approach_count", "communication_count"],
        )

    def test_non_wv_entry_form_hides_split_counts(self):
        un_department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=un_department)
        form = MemberDailyMetricEntryForm(
            member=self.member,
            initial={"department": un_department},
        )
        self.assertIn("result_count", form.fields)
        self.assertNotIn("cs_count", form.fields)
        self.assertNotIn("refugee_count", form.fields)

    def test_dashboard_can_switch_to_period_scope(self):
        Period.objects.create(
            month=date(2026, 3, 1),
            name="第1路程",
            status="active",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 15),
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 2, 18),
            approach_count=2,
            communication_count=1,
            support_amount=1000,
            cs_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 5),
            approach_count=8,
            communication_count=4,
            support_amount=2500,
            cs_count=2,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "period"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "今路程")
        self.assertContains(response, "第1路程")
        self.assertContains(response, "今路程の自己ベスト")
        self.assertContains(response, "アプローチ 平均/合計")
        self.assertNotContains(response, "活動中")
        self.assertContains(response, "fa-arrow-trend-up")
        self.assertContains(response, "fa-arrow-trend-down")
        self.assertContains(response, "+100.0%")

    def test_today_scope_without_target_shows_goal_cta(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "目標を入力")
        self.assertContains(response, "未入力")

    def test_dashboard_custom_scope_defaults_to_lifetime_and_accepts_date_range(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 2),
            approach_count=3,
            communication_count=2,
            support_amount=1200,
            cs_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 8),
            approach_count=5,
            communication_count=4,
            support_amount=2200,
            cs_count=2,
            refugee_count=1,
        )
        self.client.force_login(self.user)
        lifetime_response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "custom"})
        self.assertEqual(lifetime_response.status_code, 200)
        self.assertContains(lifetime_response, "期間指定")
        self.assertContains(lifetime_response, "生涯")
        self.assertContains(lifetime_response, 'name="start_date"')
        self.assertNotContains(lifetime_response, "目標達成率")
        self.assertNotContains(lifetime_response, "未入力")
        self.assertNotContains(lifetime_response, "fa-arrow-trend-up")
        self.assertNotContains(lifetime_response, "fa-arrow-trend-down")
        self.assertContains(lifetime_response, "合計CS/難民")
        self.assertContains(lifetime_response, "合計金額")
        self.assertContains(lifetime_response, "一日平均CS/難民")
        self.assertContains(lifetime_response, "一日平均金額")
        filtered_response = self.client.get(
            reverse("dairymetrics_dashboard"),
            {"scope": "custom", "start_date": "2026-03-08", "end_date": "2026-03-08"},
        )
        self.assertEqual(filtered_response.status_code, 200)
        self.assertContains(filtered_response, "2026/03/08 - 2026/03/08")
        self.assertContains(filtered_response, "CS 2 / 難民 1")
        self.assertContains(filtered_response, "2,200")
        self.assertContains(filtered_response, "一日平均金額")
        self.assertNotContains(filtered_response, "目標達成率")
        self.assertNotContains(filtered_response, "fa-arrow-trend-up")


class DairyMetricsAdminTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="admin_user", password="pass123", is_staff=True)
        self.member = Member.objects.create(name="Member Three")
        self.department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=self.department)

    def test_admin_overview_requires_staff(self):
        response = self.client.get(reverse("dairymetrics_admin_overview"))
        self.assertRedirects(response, reverse("dairymetrics_login"))

    def test_admin_can_create_adjustment(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("dairymetrics_adjustment_create"),
            {
                "member": self.member.id,
                "department": self.department.id,
                "target_date": "2026-03-09",
                "source_type": "postal",
                "approach_count": 0,
                "communication_count": 0,
                "result_count": 1,
                "support_amount": 5000,
                "cs_count": 0,
                "refugee_count": 0,
                "note": "late postal",
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_admin_overview") + "?month=2026-03")
        adjustment = MetricAdjustment.objects.get()
        self.assertEqual(adjustment.created_by, self.admin)
        self.assertEqual(adjustment.source_type, "postal")

    def test_admin_overview_shows_activity_status(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=1,
            support_amount=1000,
            activity_closed=True,
            activity_closed_at=timezone.now(),
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dairymetrics_admin_overview"), {"month": "2026-03"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "活動終了")
