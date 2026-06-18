import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.common.test_helpers import AppTestMixin
from apps.mail.models import MailDepartmentRouting, MailIntegrationSetting, MailSendHistory, MailRecipientGroup
from apps.targets.models import (
    DepartmentMonthTarget,
    DepartmentPeriodTarget,
    MonthTargetMetricValue,
    Period,
    PeriodTargetMetricValue,
    TARGET_STATUS_ACTIVE,
    TARGET_STATUS_FINISHED,
    TARGET_STATUS_PLANNED,
    TargetMetric,
)

from .forms import MemberDailyMetricEntryForm
from .models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)


class DairyMetricsLoginTests(AppTestMixin, TestCase):
    DEFAULT_PASSWORD = "pass123"

    def setUp(self):
        self.department = self.create_department("UN")
        self.user, self.member = self.create_member_user(
            username="member1",
            password="pass123",
            name="Member One",
            department=self.department,
        )
        self.admin = self.create_user("dm_admin", password="pass123", is_staff=True)

    def test_member_can_login(self):
        response = self.client.post(
            reverse("dairymetrics_login"),
            {"login_id": "member1", "password": "pass123"},
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard"))

    def test_non_member_user_is_rejected(self):
        self.create_user("outsider", password="pass123")
        response = self.client.post(
            reverse("dairymetrics_login"),
            {"login_id": "outsider", "password": "pass123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DairyMetrics を利用できるメンバーではありません。")

    def test_admin_redirects_to_admin_overview_after_login(self):
        response = self.client.post(
            reverse("dairymetrics_login"),
            {"login_id": "dm_admin", "password": "pass123"},
        )
        self.assertRedirects(response, reverse("dairymetrics_admin_overview"))

    def test_authenticated_admin_visiting_login_redirects_to_admin_overview(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dairymetrics_login"))
        self.assertRedirects(response, reverse("dairymetrics_admin_overview"))

    def test_dairymetrics_logout_redirects_to_performance_login(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_logout"))

        self.assertRedirects(response, reverse("performance_login"))

    def test_entry_v2_transaction_demo_can_save_un_transaction(self):
        entry_date = timezone.localdate()
        self.client.force_login(self.user)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_transaction",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "support_amount": "3000",
                "location": "渋谷駅前",
                "age_band": MemberMetricTransaction.AGE_BAND_SEVENTIES,
                "gender": MemberMetricTransaction.GENDER_FEMALE,
                "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                "comment": "UNテストコメント",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=transaction",
        )

    def test_entry_v2_transaction_demo_blocks_duplicate_un_transaction_save(self):
        entry_date = timezone.localdate()
        self.client.force_login(self.user)
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_SEVENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="UNテストコメント",
        )

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_transaction",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "support_amount": "3000",
                "location": "渋谷駅前",
                "age_band": MemberMetricTransaction.AGE_BAND_SEVENTIES,
                "gender": MemberMetricTransaction.GENDER_FEMALE,
                "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                "comment": "UNテストコメント",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(MemberMetricTransaction.objects.filter(entry=entry).count(), 1)
        self.assertContains(response, "同じ内容の決済が既に登録されています")
        self.assertContains(response, "登録せずにメールだけ送信")

    def test_entry_v2_transaction_demo_can_send_mail_for_duplicate_existing_transaction(self):
        entry_date = timezone.localdate()
        self.client.force_login(self.user)
        self.member.email = "member@example.com"
        self.member.save(update_fields=["email"])
        MailIntegrationSetting.objects.create(
            sender_email="sender@example.com",
            sender_name="Sender",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            is_active=True,
        )
        recipient_group = MailRecipientGroup.objects.create(name="共有C", department=self.department, is_active=True)
        recipient_group.members.add(self.member)
        MailDepartmentRouting.objects.create(department=self.department, recipient_group=recipient_group)
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_SEVENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="UNテストコメント",
        )

        with patch("apps.mail.services._send_via_gmail", return_value="gmail-duplicate-1"):
            response = self.client.post(
                reverse("dairymetrics_entry_v2_transaction_demo"),
                {
                    "action": "send_duplicate_transaction_mail",
                    "department_code": self.department.code,
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "duplicate_transaction_id": str(transaction.id),
                },
            )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=mail_sent",
        )
        self.assertEqual(MemberMetricTransaction.objects.filter(entry=entry).count(), 1)
        history = MailSendHistory.objects.get(transaction=transaction)
        self.assertEqual(history.status, MailSendHistory.STATUS_SENT)

    def test_entry_v2_transaction_demo_hides_wv_fields_for_un_department(self):
        entry_date = timezone.localdate()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "CS口数")
        self.assertNotContains(response, "難民支援金額")
        self.assertNotContains(response, "区分")

    def test_entry_v2_personal_setup_fields_ajax_shows_un_count_field(self):
        entry_date = timezone.localdate()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_personal_setup_fields"),
            {
                "department": str(self.department.id),
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "daily_target_count": "2",
                "daily_target_amount": "4000",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('name="daily_target_count"', payload["setup_html"])
        self.assertNotIn('name="daily_target_cs_count"', payload["setup_html"])
        self.assertNotIn('name="daily_target_refugee_count"', payload["setup_html"])

    def test_entry_v2_personal_setup_fields_ajax_shows_wv_split_count_fields(self):
        wv_department = self.create_department("WV")
        MemberDepartment.objects.create(member=self.member, department=wv_department)
        entry_date = timezone.localdate()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_personal_setup_fields"),
            {
                "department": str(wv_department.id),
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "daily_target_cs_count": "2",
                "daily_target_refugee_count": "1",
                "daily_target_amount": "4000",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('name="daily_target_cs_count"', payload["setup_html"])
        self.assertIn('name="daily_target_refugee_count"', payload["setup_html"])
        self.assertNotIn('name="daily_target_count"', payload["setup_html"])

    def test_entry_v2_personal_setup_fields_ajax_switches_department_target_form_context(self):
        wv_department = self.create_department("WV")
        MemberDepartment.objects.create(member=self.member, department=wv_department)
        entry_date = timezone.localdate()
        self.client.force_login(self.user)
        DepartmentDailyMetricSummary.objects.create(
            department=wv_department,
            entry_date=entry_date,
            daily_target_amount=9000,
        )

        response = self.client.get(
            reverse("dairymetrics_entry_v2_personal_setup_fields"),
            {
                "department": str(wv_department.id),
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "department_daily_target_amount": "9000",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(f'name="department_code" value="{wv_department.code}"', payload["department_target_html"])
        self.assertIn('name="daily_target_amount"', payload["department_target_html"])
        self.assertIn('value="9000"', payload["department_target_html"])
        self.assertIn('>15,000円<', payload["department_target_html"])
        self.assertIn('>30,000円<', payload["department_target_html"])
        self.assertNotIn('>10,000円<', payload["department_target_html"])

    def test_entry_v2_transaction_demo_defaults_to_existing_entry_department_for_day(self):
        wv_department = self.create_department("WV")
        MemberDepartment.objects.create(member=self.member, department=wv_department)
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=wv_department,
            entry_date=entry_date,
            daily_target_cs_count=2,
            daily_target_refugee_count=1,
            daily_target_amount=9000,
            support_amount=0,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_entry_v2_transaction_demo"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_department_code"], "WV")
        self.assertContains(response, "CS口数")
        self.assertNotContains(response, "決済金額")


class DairyMetricsDashboardTests(AppTestMixin, TestCase):
    DEFAULT_PASSWORD = "pass123"

    def setUp(self):
        self.department = self.create_department("WV")
        self.user, self.member = self.create_member_user(
            username="member2",
            password="pass123",
            name="Member Two",
            department=self.department,
        )

    def create_dashboard_member(self, *, username: str, name: str, department=None):
        user, member = self.create_member_user(
            username=username,
            password="pass123",
            name=name,
            department=department or self.department,
        )
        return user, member

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
        self.assertContains(response, "4,000")
        self.assertContains(response, "3")
        self.assertContains(response, "10")
        self.assertContains(response, "過去7日の推移")
        self.assertContains(response, "現場 CS 2 / 難民 1")
        self.assertContains(response, "今日:")
        self.assertContains(response, "目標達成率")
        self.assertContains(response, "60.0%")
        self.assertContains(response, "残り 2")
        self.assertContains(response, "3/5")
        self.assertContains(response, "4,000/8,000")
        self.assertContains(response, "スコアを見る")
        self.assertNotContains(response, "今日の順位")
        self.assertContains(response, ">アプローチ<")
        self.assertContains(response, ">コミュニケーション<")
        self.assertContains(response, ">支援金額<")
        self.assertContains(response, ">コミュ率<")
        self.assertContains(response, ">参加率<")
        self.assertContains(response, ">平均支援額<")
        self.assertContains(response, "60.0%")
        self.assertContains(response, "50.0%")
        self.assertContains(response, "1,333.3")
        self.assertNotContains(response, "アプローチ 平均/合計")
        self.assertNotContains(response, "今日の自己ベスト")
        self.assertNotContains(response, "伸びた項目")
        self.assertNotContains(response, "落ちた項目")
        self.assertNotContains(response, "今日のアプローチ")
        self.assertNotContains(response, "今日のコミュニケーション")
        self.assertNotContains(response, "今日の支援金額")
        self.assertContains(response, "過去7日の推移")
        self.assertNotContains(response, "fa-sparkles")

    def test_today_scope_excludes_return_totals(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=8,
            communication_count=5,
            support_amount=1200,
            cs_count=2,
            refugee_count=1,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="postal",
            return_postal_count=2,
            return_postal_amount=3000,
            return_qr_count=1,
            return_qr_amount=800,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">支援金額<")
        self.assertContains(response, ">1,200<")
        self.assertContains(response, "現場 CS 2 / 難民 1")
        self.assertNotContains(response, "郵送 2")

    def test_month_scope_includes_return_totals(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=8,
            communication_count=5,
            support_amount=1200,
            cs_count=2,
            refugee_count=1,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="postal",
            return_postal_count=2,
            return_postal_amount=3000,
            return_qr_count=1,
            return_qr_amount=800,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "month"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">6<")
        self.assertContains(response, ">5,000<")
        self.assertContains(response, "現場 CS 2 / 難民 1 / 郵送 2 / QR 1")

    def test_goal_card_highlights_when_both_targets_are_completed(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            support_amount=9000,
            daily_target_count=3,
            daily_target_amount=8000,
            cs_count=2,
            refugee_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is-complete")
        self.assertContains(response, "fa-crown")

    def test_entry_v2_demo_requires_login(self):
        response = self.client.get(reverse("dairymetrics_entry_v2_demo"))
        self.assertRedirects(response, reverse("performance_login"))

    def test_entry_v2_demo_prefills_total_count_from_existing_entry(self):
        self.department.code = "UN"
        self.department.save(update_fields=["code"])
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=7,
            support_amount=12000,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_demo"),
            {"department": self.department.code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "実績入力プレビュー")
        self.assertContains(response, 'value="7"', html=False)
        self.assertContains(response, 'value="12000"', html=False)
        self.assertContains(response, "年代内訳")
        self.assertContains(response, "男女比")
        self.assertContains(response, "国籍分類")

    def test_entry_v2_transaction_demo_requires_login(self):
        response = self.client.get(reverse("dairymetrics_entry_v2_transaction_demo"))
        self.assertRedirects(response, reverse("performance_login"))

    def test_entry_v2_transaction_demo_shows_goal_cards_and_mail_preview_flow(self):
        self.department.code = "UN"
        self.department.name = "UN"
        self.department.save(update_fields=["code", "name"])
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            result_count=4,
            support_amount=8000,
            daily_target_amount=12000,
        )
        teammate_user = get_user_model().objects.create_user(username="member2_sample", password="pass123")
        teammate = Member.objects.create(name="Member Sample", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=entry_date,
            support_amount=5000,
            daily_target_amount=10000,
        )
        period = Period.objects.create(
            month=entry_date.replace(day=1),
            name="2026年5月 第2次路程",
            status=TARGET_STATUS_ACTIVE,
            start_date=entry_date - timedelta(days=2),
            end_date=entry_date + timedelta(days=3),
        )
        DepartmentPeriodTarget.objects.create(
            department=self.department,
            period=period,
            target_amount=50000,
        )
        DepartmentMonthTarget.objects.create(
            department=self.department,
            target_month=entry_date.replace(day=1),
            target_amount=200000,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "決済登録")
        self.assertContains(response, "全体の日目標")
        self.assertContains(response, "路程目標")
        self.assertContains(response, "月目標")
        self.assertContains(response, "今日の活動現場")
        self.assertContains(response, "修正する")
        self.assertContains(response, "決済を1件登録する")
        self.assertContains(response, "送信本文プレビュー")
        self.assertContains(response, "登録してメール送信")
        self.assertContains(response, "登録して閉じる")
        self.assertContains(response, "13,000")
        self.assertContains(response, "目標設定")
        self.assertContains(response, "部署全体の日目標を入力")
        self.assertContains(response, "1,000円")
        self.assertContains(response, "5,000円")
        self.assertContains(response, "直接入力")
        self.assertContains(response, "10代")
        self.assertContains(response, "70代")
        self.assertContains(response, "80代")
        self.assertContains(response, "90代以上")
        self.assertContains(response, "学生")
        self.assertContains(response, "本日の決済一覧を見る")
        self.assertContains(response, "当日送信メールを見る")
        self.assertContains(response, "活動終了時の最終実績を確認")
        self.assertNotContains(response, "今日の集計箱")

    def test_entry_v2_transaction_demo_reads_period_and_month_targets_from_metric_values(self):
        self.department.code = "UN"
        self.department.name = "UN"
        self.department.save(update_fields=["code", "name"])
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            result_count=2,
            support_amount=8000,
            daily_target_amount=12000,
        )
        period = Period.objects.create(
            month=entry_date.replace(day=1),
            name="2026年5月 第2次路程",
            status=TARGET_STATUS_ACTIVE,
            start_date=entry_date - timedelta(days=2),
            end_date=entry_date + timedelta(days=3),
        )
        amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
            is_active=True,
        )
        PeriodTargetMetricValue.objects.create(
            period=period,
            department=self.department,
            metric=amount_metric,
            value=30000,
        )
        MonthTargetMetricValue.objects.create(
            department=self.department,
            target_month=entry_date.replace(day=1),
            metric=amount_metric,
            value=120000,
            status=TARGET_STATUS_ACTIVE,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "30,000")
        self.assertContains(response, "120,000")

    def test_entry_v2_transaction_demo_shows_department_member_activity_lists(self):
        self.department.code = "UN"
        self.department.name = "UN"
        self.department.save(update_fields=["code", "name"])
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
            result_count=1,
            support_amount=1500,
            location_name="渋谷駅前",
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        active_user = get_user_model().objects.create_user(username="member_v2_active", password="pass123")
        active_member = Member.objects.create(name="Member Active V2", user=active_user)
        MemberDepartment.objects.create(member=active_member, department=self.department)
        closed_user = get_user_model().objects.create_user(username="member_v2_closed", password="pass123")
        closed_member = Member.objects.create(name="Member Closed V2", user=closed_user)
        MemberDepartment.objects.create(member=closed_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=active_member,
            department=self.department,
            entry_date=entry_date,
            result_count=2,
            support_amount=3000,
            daily_target_amount=8000,
            location_name="新宿駅前",
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        MemberDailyMetricEntry.objects.create(
            member=closed_member,
            department=self.department,
            entry_date=entry_date,
            result_count=3,
            support_amount=4500,
            daily_target_amount=9000,
            location_name="池袋駅前",
            activity_closed=True,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本日のメンバー状況")
        self.assertContains(response, "活動中")
        self.assertContains(response, "活動終了")
        self.assertContains(response, "Member Active V2")
        self.assertContains(response, "Member Closed V2")
        self.assertContains(response, "新宿駅前")
        self.assertContains(response, "池袋駅前")
        self.assertContains(response, "2件")
        self.assertContains(response, "3,000円 / 8,000円")
        self.assertContains(response, "4,500円 / 9,000円")
        self.assertNotContains(response, "件数 2件")
        self.assertNotContains(response, "金額 3,000円")
        self.assertContains(response, reverse("performance_member_insight", args=[active_member.id, self.department.id]))
        self.assertContains(response, reverse("performance_member_insight", args=[closed_member.id, self.department.id]))

    def test_entry_v2_transaction_demo_shows_wv_count_breakdown_and_type_field(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
            result_count=2,
            cs_count=1,
            refugee_count=1,
            support_amount=3000,
            location_name="新宿駅前",
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        teammate_user = get_user_model().objects.create_user(username="member_v2_wv", password="pass123")
        teammate = Member.objects.create(name="Member WV", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=entry_date,
            result_count=3,
            cs_count=2,
            refugee_count=1,
            support_amount=4500,
            location_name="池袋駅前",
            activity_closed=True,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "区分")
        self.assertContains(response, "個人のCS件数目標")
        self.assertContains(response, "個人の難民件数目標")
        self.assertContains(response, "件数 CS 1 / 難民 1 / 合計 2")
        self.assertContains(response, "件数 CS 2 / 難民 1 / 合計 3")

    def test_entry_v2_transaction_demo_shows_separate_department_target_setup_when_missing(self):
        self.department.code = "UN"
        self.department.name = "UN"
        self.department.save(update_fields=["code", "name"])
        entry_date = timezone.localdate()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "目標設定")
        self.assertContains(response, "部署全体の日目標を入力")
        self.assertContains(response, "全体目標の対象日")
        self.assertContains(response, "全体目標を保存")
        self.assertNotContains(response, "決済を1件登録する")
        self.assertNotContains(response, "入力内容を確定")
        self.assertNotContains(response, "<span class=\"muted\">対象</span>", html=True)

    def test_entry_v2_transaction_demo_prefills_targets_from_previous_day(self):
        self.client.force_login(self.user)
        entry_date = timezone.localdate()
        previous_date = entry_date - timedelta(days=1)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=previous_date,
            daily_target_count=4,
            daily_target_cs_count=1,
            daily_target_refugee_count=3,
            daily_target_amount=3500,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=previous_date,
            daily_target_amount=15500,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="v2-personal-target-cs-count" type="number" min="0" step="1" name="daily_target_cs_count" value="1"', html=False)
        self.assertContains(response, 'id="v2-personal-target-refugee-count" type="number" min="0" step="1" name="daily_target_refugee_count" value="3"', html=False)
        self.assertContains(response, 'id="v2-personal-target-amount-hidden" value="3500"', html=False)
        self.assertContains(response, 'id="v2-dept-target-amount-hidden" value="15500"', html=False)

    def test_entry_v2_transaction_demo_uses_fallback_target_defaults_without_previous_day(self):
        self.client.force_login(self.user)
        entry_date = timezone.localdate()

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="v2-personal-date" class="dairymetrics-date-input" type="date" name="entry_date" value="{entry_date.strftime("%Y-%m-%d")}"', html=False)
        self.assertContains(response, f'id="v2-dept-target-date" class="dairymetrics-date-input" type="date" name="entry_date" value="{entry_date.strftime("%Y-%m-%d")}"', html=False)
        self.assertContains(response, 'id="v2-personal-target-cs-count" type="number" min="0" step="1" name="daily_target_cs_count" value="0"', html=False)
        self.assertContains(response, 'id="v2-personal-target-refugee-count" type="number" min="0" step="1" name="daily_target_refugee_count" value="1"', html=False)
        self.assertContains(response, 'id="v2-personal-target-amount-hidden" value="3000"', html=False)
        self.assertContains(response, 'id="v2-dept-target-amount-hidden" value="10000"', html=False)

    def test_entry_v2_transaction_demo_saves_personal_target_entry(self):
        self.client.force_login(self.user)
        entry_date = timezone.localdate()

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_personal_setup",
                "department": self.department.id,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "location_name": "渋谷駅前",
                "daily_target_cs_count": "2",
                "daily_target_refugee_count": "1",
                "daily_target_amount": "6000",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=personal_setup",
        )
        entry = MemberDailyMetricEntry.objects.get(member=self.member, department=self.department, entry_date=entry_date)
        self.assertEqual(entry.daily_target_count, 3)
        self.assertEqual(entry.daily_target_cs_count, 2)
        self.assertEqual(entry.daily_target_refugee_count, 1)
        self.assertEqual(entry.daily_target_amount, 6000)
        self.assertEqual(entry.location_name, "渋谷駅前")

    def test_entry_v2_transaction_demo_updates_personal_target_from_progress_card(self):
        self.client.force_login(self.user)
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_personal_setup",
                "department": self.department.id,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "location_name": "池袋駅前",
                "daily_target_cs_count": "3",
                "daily_target_refugee_count": "2",
                "daily_target_amount": "9000",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=personal_setup",
        )
        entry = MemberDailyMetricEntry.objects.get(member=self.member, department=self.department, entry_date=entry_date)
        self.assertEqual(entry.daily_target_count, 5)
        self.assertEqual(entry.daily_target_cs_count, 3)
        self.assertEqual(entry.daily_target_refugee_count, 2)
        self.assertEqual(entry.daily_target_amount, 9000)
        self.assertEqual(entry.location_name, "池袋駅前")

    def test_entry_v2_transaction_demo_prefills_transaction_location_from_activity_location(self):
        self.client.force_login(self.user)
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
            location_name="新宿駅前",
        )

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="v2-transaction-location" type="hidden" name="location" value="新宿駅前"', html=False)

    def test_entry_v2_transaction_demo_saves_department_daily_target_summary(self):
        self.client.force_login(self.user)
        entry_date = timezone.localdate() + timedelta(days=1)

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_department_target",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "daily_target_amount": "20000",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=department_target",
        )
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry_date)
        self.assertEqual(summary.daily_target_amount, 20000)
        self.assertEqual(summary.created_by, self.member)
        self.assertEqual(summary.updated_by, self.member)

    def test_entry_v2_transaction_demo_saves_transaction_and_updates_totals(self):
        entry_date = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_transaction",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "wv_result_type": MemberMetricTransaction.WV_RESULT_BOTH,
                "wv_cs_count": "2",
                "wv_refugee_amount": "1800",
                "location": "渋谷駅前",
                "age_band": MemberMetricTransaction.AGE_BAND_SEVENTIES,
                "gender": MemberMetricTransaction.GENDER_FEMALE,
                "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                "comment": "テストコメント",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=transaction",
        )
        entry = MemberDailyMetricEntry.objects.get(member=self.member, department=self.department, entry_date=entry_date)
        self.assertEqual(entry.result_count, 3)
        self.assertEqual(entry.cs_count, 2)
        self.assertEqual(entry.refugee_count, 1)
        self.assertEqual(entry.support_amount, 10800)
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry_date)
        self.assertEqual(summary.result_count, 3)
        self.assertEqual(summary.support_amount, 10800)

    def test_entry_v2_transaction_demo_deletes_transaction_and_reverts_totals(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_BOTH,
            wv_cs_count=2,
            wv_refugee_amount=1800,
            location="渋谷駅前",
            age_band=MemberMetricTransaction.AGE_BAND_SEVENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            comment="削除テスト",
        )
        MailSendHistory.objects.create(
            department=self.department,
            activity_date=entry_date,
            sender_member=self.member,
            transaction=transaction,
            subject_snapshot="件名",
            body_snapshot="本文",
            sent_to_snapshot="a@example.com",
            status=MailSendHistory.STATUS_SENT,
            sent_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "delete_transaction",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "transaction_id": str(transaction.id),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=transaction_deleted",
        )
        self.assertFalse(MemberMetricTransaction.objects.filter(id=transaction.id).exists())
        self.assertFalse(MailSendHistory.objects.filter(transaction_id=transaction.id).exists())
        entry.refresh_from_db()
        self.assertEqual(entry.result_count, 0)
        self.assertEqual(entry.cs_count, 0)
        self.assertEqual(entry.refugee_count, 0)
        self.assertEqual(entry.support_amount, 0)
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry_date)
        self.assertEqual(summary.result_count, 0)
        self.assertEqual(summary.support_amount, 0)

    def test_entry_v2_transaction_demo_closeout_updates_entry_and_shows_department_mail_history(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        self.member.email = "member-two@example.com"
        self.member.save(update_fields=["email"])
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=1,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            is_student=True,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="駅前",
            comment="一体化",
        )
        entry.recalculate_from_transactions()
        recipient_group = MailRecipientGroup.objects.create(name="共有A")
        MailSendHistory.objects.create(
            department=self.department,
            activity_date=entry_date,
            sender_member=self.member,
            transaction=transaction,
            recipient_group=recipient_group,
            subject_snapshot="5/14Memberです(WV)",
            body_snapshot="CS1口 4,500円",
            status=MailSendHistory.STATUS_SENT,
            sent_at=timezone.now(),
        )
        self.client.force_login(self.user)

        closeout_response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_closeout",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "approach_count": "12",
                "communication_count": "7",
            },
        )

        self.assertRedirects(
            closeout_response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=closeout",
        )
        entry.refresh_from_db()
        self.assertEqual(entry.approach_count, 12)
        self.assertEqual(entry.communication_count, 7)
        self.assertTrue(entry.activity_closed)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )
        self.assertContains(response, self.member.name)

    def test_wv_entry_v2_flow_reflects_in_performance_and_report_views(self):
        entry_date = timezone.localdate()
        self.client.force_login(self.user)

        personal_response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_personal_setup",
                "department": str(self.department.id),
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "location_name": "渋谷駅前",
                "daily_target_cs_count": "2",
                "daily_target_refugee_count": "1",
                "daily_target_amount": "12000",
            },
        )
        self.assertRedirects(
            personal_response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=personal_setup",
        )

        department_response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_department_target",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "daily_target_amount": "30000",
            },
        )
        self.assertRedirects(
            department_response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=department_target",
        )

        transaction_response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_transaction",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "wv_result_type": MemberMetricTransaction.WV_RESULT_BOTH,
                "wv_cs_count": "1",
                "wv_refugee_amount": "1800",
                "age_band": MemberMetricTransaction.AGE_BAND_TWENTIES,
                "gender": MemberMetricTransaction.GENDER_FEMALE,
                "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                "comment": "反映テスト",
            },
        )
        self.assertRedirects(
            transaction_response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=transaction",
        )

        closeout_response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_closeout",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "approach_count": "12",
                "communication_count": "7",
            },
        )
        self.assertRedirects(
            closeout_response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=closeout",
        )

        performance_response = self.client.get(reverse("performance_member_dashboard"))
        self.assertEqual(performance_response.status_code, 200)
        self.assertContains(performance_response, "6,300円")
        self.assertContains(performance_response, "CS 1件 / 難民 1件")

        metrics_response = self.client.get(
            reverse("dairymetrics_metrics_v2_demo"),
            {"department": self.department.code},
        )
        self.assertEqual(metrics_response.status_code, 200)
        self.assertContains(metrics_response, "CS件数")
        self.assertContains(metrics_response, "難民件数")

        report_response = self.client.get(reverse("report_wv"))
        self.assertEqual(report_response.status_code, 200)
        self.assertContains(report_response, 'value="1"', html=False)
        self.assertContains(report_response, 'value="6300"', html=False)

    @patch("apps.mail.services._send_via_gmail", return_value="gmail-transaction-1")
    def test_entry_v2_transaction_demo_mock_send_creates_mail_history_and_shows_it(self, mocked_send):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_refugee_amount=1500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            is_student=True,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="テストコメント",
        )
        entry.recalculate_from_transactions()
        self.client.force_login(self.user)
        self.member.email = "member@example.com"
        self.member.save(update_fields=["email"])
        MailIntegrationSetting.objects.create(
            sender_email="sender@example.com",
            sender_name="Sender",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            is_active=True,
        )
        recipient_group = MailRecipientGroup.objects.create(name="共有B", department=self.department, is_active=True)
        recipient_group.members.add(self.member)
        MailDepartmentRouting.objects.create(department=self.department, recipient_group=recipient_group)

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "send_transaction_mail",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "preview_transaction_id": str(transaction.id),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=mail_sent",
        )
        history = MailSendHistory.objects.get(transaction=transaction, recipient_group=recipient_group)
        self.assertEqual(history.status, MailSendHistory.STATUS_SENT)
        self.assertEqual(history.sender_member, self.member)
        self.assertIn(self.member.email, history.sent_to_snapshot)
        mocked_send.assert_called_once()
        self.assertEqual(mocked_send.call_args.kwargs["to_recipients"], ["sender@example.com"])
        self.assertEqual(mocked_send.call_args.kwargs["cc_recipients"], [self.member.email])

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )
        self.assertContains(response, self.member.name)
        self.assertContains(response, "1,500円")
        self.assertContains(response, history.body_snapshot)

    def test_entry_v2_transaction_demo_mock_send_without_mail_group_still_saves_history(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_refugee_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_SEVENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="送信テスト",
        )
        entry.recalculate_from_transactions()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "send_transaction_mail",
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "preview_transaction_id": str(transaction.id),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=mail_failed",
        )
        history = MailSendHistory.objects.get(transaction=transaction)
        self.assertEqual(history.status, MailSendHistory.STATUS_FAILED)
        self.assertIsNone(history.recipient_group)
        self.assertEqual(history.error_code, "missing_recipient_group")
        self.assertEqual(history.error_message, "送信先グループが未設定です。")

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )
        self.assertContains(response, self.member.name)
        self.assertContains(response, "送信失敗")
        self.assertContains(response, "送信先グループが未設定です。")

    def test_entry_v2_transaction_demo_mail_failure_creates_failed_history_and_badge(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_refugee_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_SEVENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="送信失敗テスト",
        )
        self.client.force_login(self.user)

        with patch("apps.dairymetrics.views.send_transaction_mail", side_effect=RuntimeError("gmail timeout")):
            response = self.client.post(
                reverse("dairymetrics_entry_v2_transaction_demo"),
                {
                    "action": "send_transaction_mail",
                    "department_code": self.department.code,
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "preview_transaction_id": str(transaction.id),
                },
            )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=mail_failed",
        )
        history = MailSendHistory.objects.get(transaction=transaction)
        self.assertEqual(history.status, MailSendHistory.STATUS_FAILED)
        self.assertEqual(history.error_code, "RuntimeError")
        self.assertEqual(history.error_message, "gmail timeout")

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )
        self.assertContains(response, "送信失敗")
        self.assertContains(response, "gmail timeout")
        self.assertContains(response, "再送")

    def test_entry_v2_transaction_demo_can_edit_and_resend_sent_mail(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_refugee_amount=2500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="初回送信",
        )
        entry.recalculate_from_transactions()
        first_history = MailSendHistory.objects.create(
            department=self.department,
            activity_date=entry_date,
            sender_member=self.member,
            transaction=transaction,
            subject_snapshot="初回件名",
            body_snapshot="初回本文",
            status=MailSendHistory.STATUS_SENT,
            sent_at=timezone.now(),
        )
        self.client.force_login(self.user)
        self.member.email = "member@example.com"
        self.member.save(update_fields=["email"])
        MailIntegrationSetting.objects.create(
            sender_email="sender@example.com",
            sender_name="Sender",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            is_active=True,
        )
        recipient_group = MailRecipientGroup.objects.create(name="共有C", department=self.department, is_active=True)
        recipient_group.members.add(self.member)
        MailDepartmentRouting.objects.create(department=self.department, recipient_group=recipient_group)

        with patch("apps.mail.services._send_via_gmail", return_value="gmail-transaction-2"):
            response = self.client.post(
                reverse("dairymetrics_entry_v2_transaction_demo"),
                {
                    "action": "send_transaction_mail",
                    "department_code": self.department.code,
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "preview_history_id": str(first_history.id),
                    "preview_subject": "修正版件名",
                    "preview_body": "修正版本文",
                },
            )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=mail_sent",
        )
        histories = list(MailSendHistory.objects.filter(transaction=transaction).order_by("created_at", "id"))
        self.assertEqual(len(histories), 1)
        resent_history = histories[0]
        self.assertEqual(resent_history.subject_snapshot, "修正版件名（再送）")
        self.assertEqual(resent_history.body_snapshot, "修正版本文")
        self.assertTrue(resent_history.is_resend)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )
        self.assertContains(response, "修正")
        self.assertContains(response, "再送")
        self.assertContains(response, "修正再送済み")
        self.assertContains(response, "修正版本文")
        self.assertNotContains(response, "初回本文")

    def test_entry_v2_transaction_demo_preview_body_uses_plus_after_target_is_exceeded(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=1,
            daily_target_amount=3000,
            support_amount=0,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry_date,
            daily_target_amount=10000,
            support_amount=12000,
            created_by=self.member,
            updated_by=self.member,
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="プラス確認",
        )
        entry.recalculate_from_transactions()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "日目まで +5,500円")

    def test_entry_v2_transaction_demo_preview_body_shows_wv_period_gap_in_yen(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=1,
            daily_target_amount=3000,
        )
        period = Period.objects.create(
            month=entry_date.replace(day=1),
            name="2026年6月 第1次路程",
            status=TARGET_STATUS_ACTIVE,
            start_date=entry_date - timedelta(days=1),
            end_date=entry_date + timedelta(days=1),
        )
        amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
            is_active=True,
        )
        PeriodTargetMetricValue.objects.create(
            period=period,
            department=self.department,
            metric=amount_metric,
            value=30000,
        )
        MonthTargetMetricValue.objects.create(
            target_month=entry_date.replace(day=1),
            department=self.department,
            metric=amount_metric,
            value=100000,
            status=TARGET_STATUS_ACTIVE,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=1,
            support_amount=4500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="WV路程確認",
        )
        entry.recalculate_from_transactions()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "department": self.department.code,
                "date": entry_date.strftime("%Y-%m-%d"),
                "preview_tx": str(transaction.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "路目まで 25,500円")
        self.assertContains(response, "閉じて内容を修正")

    def test_entry_v2_transaction_demo_preview_body_uses_amount_like_metric_codes_for_wv_targets(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=1,
            daily_target_amount=3000,
        )
        period = Period.objects.create(
            month=entry_date.replace(day=1),
            name="2026年6月 第1次路程",
            status=TARGET_STATUS_ACTIVE,
            start_date=entry_date - timedelta(days=1),
            end_date=entry_date + timedelta(days=1),
        )
        amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="support_amount",
            label="金額",
            unit="円",
            display_order=1,
            is_active=True,
        )
        PeriodTargetMetricValue.objects.create(
            period=period,
            department=self.department,
            metric=amount_metric,
            value=66000,
        )
        DepartmentPeriodTarget.objects.create(
            department=self.department,
            period=period,
            target_amount=6600,
        )
        MonthTargetMetricValue.objects.create(
            target_month=entry_date.replace(day=1),
            department=self.department,
            metric=amount_metric,
            value=100000,
            status=TARGET_STATUS_ACTIVE,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=1,
            support_amount=4500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="WVコード確認",
        )
        entry.recalculate_from_transactions()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "department": self.department.code,
                "date": entry_date.strftime("%Y-%m-%d"),
                "preview_tx": str(transaction.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "路目まで 61,500円")
        self.assertNotContains(response, "路目まで 2,100円")

    def test_entry_v2_transaction_demo_shows_modified_unsent_after_editing_sent_transaction(self):
        entry_date = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_date,
            daily_target_count=2,
            daily_target_amount=4000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_refugee_amount=2000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="初回",
        )
        entry.recalculate_from_transactions()
        MailSendHistory.objects.create(
            department=self.department,
            activity_date=entry_date,
            sender_member=self.member,
            transaction=transaction,
            subject_snapshot="初回件名",
            body_snapshot="初回本文",
            status=MailSendHistory.STATUS_SENT,
            sent_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_transaction",
                "transaction_id": str(transaction.id),
                "department_code": self.department.code,
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "wv_result_type": MemberMetricTransaction.WV_RESULT_BOTH,
                "wv_cs_count": "2",
                "wv_refugee_amount": "2500",
                "location": "渋谷駅前",
                "age_band": MemberMetricTransaction.AGE_BAND_TWENTIES,
                "gender": MemberMetricTransaction.GENDER_FEMALE,
                "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                "comment": "修正後",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('dairymetrics_entry_v2_transaction_demo')}?department={self.department.code}&date={entry_date.strftime('%Y-%m-%d')}&saved=transaction",
        )
        response = self.client.get(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {"department": self.department.code, "date": entry_date.strftime("%Y-%m-%d")},
        )
        self.assertContains(response, "修正済み未送信")

    def test_comparison_page_shows_ranking_metrics(self):
        teammate_user = get_user_model().objects.create_user(username="member2c", password="pass123")
        teammate = Member.objects.create(name="Member Compare", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        third_user = get_user_model().objects.create_user(username="member2d", password="pass123")
        third = Member.objects.create(name="Member Third", user=third_user)
        MemberDepartment.objects.create(member=third, department=self.department)
        fourth_user = get_user_model().objects.create_user(username="member2e", password="pass123")
        fourth = Member.objects.create(name="Member Fourth", user=fourth_user)
        MemberDepartment.objects.create(member=fourth, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=3,
            communication_count=2,
            support_amount=900,
            cs_count=1,
            refugee_count=0,
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=9,
            communication_count=6,
            support_amount=3200,
            cs_count=2,
            refugee_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=third,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=5,
            communication_count=4,
            support_amount=2200,
            cs_count=1,
            refugee_count=1,
            activity_closed=True,
            activity_closed_at=timezone.now(),
        )
        MemberDailyMetricEntry.objects.create(
            member=fourth,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=4,
            communication_count=3,
            support_amount=1500,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_compare"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "みんなの平均")
        self.assertContains(response, "全体平均")
        self.assertContains(response, "自分")
        self.assertContains(response, "平均との差")
        self.assertContains(response, "ランキング")
        self.assertContains(response, "fa-crown")
        self.assertContains(response, "アプローチ数")
        self.assertContains(response, "コミュニケーション数")
        self.assertContains(response, "件数")
        self.assertContains(response, "金額")
        self.assertContains(response, "平均支援額")
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "参加率")
        self.assertContains(response, "Member Compare")
        self.assertContains(response, "Member Third")
        self.assertContains(response, "Member Fourth")
        self.assertContains(response, "Member Two")
        self.assertContains(response, 'class="dairymetrics-rank-badge">4<')
        self.assertContains(response, "ダッシュボードへ戻る")

    def test_comparison_page_month_scope_shows_average_cards(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=6,
            communication_count=4,
            support_amount=3000,
            cs_count=2,
            refugee_count=1,
        )
        teammate_user = get_user_model().objects.create_user(username="member2f", password="pass123")
        teammate = Member.objects.create(name="Member Month Compare", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            approach_count=3,
            communication_count=2,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_compare"), {"scope": "month"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "みんなの平均")
        self.assertContains(response, "アプローチ数")
        self.assertContains(response, "コミュニケーション数")
        self.assertContains(response, "件数")
        self.assertContains(response, "金額")
        self.assertContains(response, "平均支援額")
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "参加率")
        self.assertContains(response, "ランキング")
        self.assertContains(response, "前月比")
        self.assertContains(response, "+100.0%")

    def test_comparison_page_rate_average_diff_uses_point_difference(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=10,
            communication_count=5,
            support_amount=1000,
            cs_count=2,
            refugee_count=0,
        )
        teammate_user = get_user_model().objects.create_user(username="member2ratediff", password="pass123")
        teammate = Member.objects.create(name="Member Rate Diff", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            approach_count=10,
            communication_count=8,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_compare"), {"scope": "month"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "-15.0%")
        self.assertContains(response, "参加率")
        self.assertContains(response, "+13.8%")

    def test_comparison_page_rate_average_diff_uses_direct_rate_gap(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=110,
            communication_count=24,
            support_amount=1000,
            cs_count=8,
            refugee_count=0,
        )
        teammate_user = get_user_model().objects.create_user(username="member2rategap", password="pass123")
        teammate = Member.objects.create(name="Member Rate Gap", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            approach_count=10,
            communication_count=5,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        third_user = get_user_model().objects.create_user(username="member2rategap3", password="pass123")
        third_member = Member.objects.create(name="Member Rate Gap Three", user=third_user)
        MemberDepartment.objects.create(member=third_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=third_member,
            department=self.department,
            entry_date=today,
            approach_count=200,
            communication_count=13,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_compare"), {"scope": "month"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "-4.3%")

    def test_comparison_page_can_show_selected_member_scores(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        teammate_user = get_user_model().objects.create_user(username="member2selected", password="pass123")
        teammate = Member.objects.create(name="Selected Compare Member", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            approach_count=8,
            communication_count=6,
            support_amount=2000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_compare"),
            {"member": teammate.id, "scope": "today"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selected Compare Memberさんのスコアページ")
        self.assertContains(response, "Selected Compare Member")
        self.assertContains(response, "自分と比較")
        self.assertContains(response, "Selected Compare MemberさんとMember Twoさんの差分")
        self.assertContains(response, "2,000")
        self.assertContains(response, "1,000")
        self.assertContains(response, "+1,000")
        self.assertContains(response, "+100.00%")
        self.assertContains(response, "2,000.0 / 1件")
        self.assertContains(response, f"?department=WV&scope=today&member={teammate.id}")
        self.assertContains(response, 'data-scope-select-submit', html=False)

    def test_comparison_page_custom_scope_can_select_saved_period(self):
        teammate_user = get_user_model().objects.create_user(username="member2period", password="pass123")
        teammate = Member.objects.create(name="Period Compare Member", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        period = Period.objects.create(
            name="第2路程",
            month=date(2026, 3, 1),
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 20),
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=date(2026, 3, 12),
            approach_count=5,
            communication_count=4,
            support_amount=2600,
            cs_count=1,
            refugee_count=1,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_compare"),
            {"member": teammate.id, "scope": "custom", "period_id": period.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "保存済み路程")
        self.assertContains(response, "第2路程")
        self.assertContains(response, f'<option value="{period.id}" selected>', html=False)

    def test_member_dashboard_custom_scope_form_posts_back_to_selected_member(self):
        teammate_user = get_user_model().objects.create_user(username="member2readonly", password="pass123")
        teammate = Member.objects.create(name="Readonly Compare Member", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        Period.objects.create(
            name="第3路程",
            month=date(2026, 3, 1),
            start_date=date(2026, 3, 21),
            end_date=date(2026, 3, 31),
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=date(2026, 3, 22),
            approach_count=4,
            communication_count=3,
            support_amount=1800,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[teammate.id]),
            {"scope": "custom"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="{reverse("dairymetrics_member_dashboard", args=[teammate.id])}"', html=False)
        self.assertContains(response, "保存済み路程")

    def test_member_dashboard_custom_scope_saved_period_select_uses_date_only_labels(self):
        period = Period.objects.create(
            name="2026年度3月 第2次路程",
            month=date(2026, 3, 1),
            start_date=date(2026, 3, 16),
            end_date=date(2026, 3, 21),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "custom"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f">{period.start_date.strftime('%Y/%m/%d')} - {period.end_date.strftime('%Y/%m/%d')}<", html=False)
        self.assertNotContains(response, period.name)

    def test_member_dashboard_period_scope_falls_back_to_latest_saved_period(self):
        today = timezone.localdate()
        target_user = get_user_model().objects.create_user(username="member-period-fallback", password="pass123")
        target_member = Member.objects.create(name="Period Fallback Member", user=target_user)
        MemberDepartment.objects.create(member=target_member, department=self.department)
        latest_period = Period.objects.create(
            name="第4路程",
            month=date(2026, 3, 1),
            start_date=today - timedelta(days=12),
            end_date=today - timedelta(days=5),
        )
        MemberDailyMetricEntry.objects.create(
            member=target_member,
            department=self.department,
            entry_date=latest_period.start_date,
            approach_count=6,
            communication_count=4,
            support_amount=2200,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[target_member.id]),
            {"scope": "period"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("今路程: 第4路程", payload["card_html"])
        self.assertNotIn('aria-disabled="true"', payload["card_html"])

    def test_comparison_ranking_detail_returns_full_modal_html(self):
        today = timezone.localdate()
        teammate_user = get_user_model().objects.create_user(username="member2g", password="pass123")
        teammate = Member.objects.create(name="Member Modal", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=3,
            communication_count=2,
            support_amount=900,
            cs_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            approach_count=6,
            communication_count=4,
            support_amount=2500,
            cs_count=2,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_compare_ranking_detail"),
            {"department": "WV", "scope": "today", "metric": "support_amount"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("金額", payload["modal_html"])
        self.assertIn("Member Modal", payload["modal_html"])
        self.assertIn("Member Two", payload["modal_html"])

    def test_comparison_average_support_amount_ranking_shows_count_denominator(self):
        today = timezone.localdate()
        teammate_user = get_user_model().objects.create_user(username="member2avgdenom", password="pass123")
        teammate = Member.objects.create(name="Member Avg Denom", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            support_amount=3000,
            cs_count=2,
            refugee_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_compare"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1,000.0 / 1件")

    def test_admin_ranking_average_support_amount_shows_count_denominator(self):
        today = timezone.localdate()
        admin = get_user_model().objects.create_user(username="dm_admin_rankavg", password="pass123", is_staff=True)
        teammate_user = get_user_model().objects.create_user(username="member2adminavg", password="pass123")
        teammate = Member.objects.create(name="Member Admin Avg", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            support_amount=4800,
            cs_count=3,
            refugee_count=1,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("dairymetrics_admin_ranking_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1,200.0 / 4件")

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
        self.assertEqual(entry.input_source, MemberDailyMetricEntry.SOURCE_MEMBER)

    def test_entry_form_promotes_admin_created_entry_to_member_source(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=5,
            input_source=MemberDailyMetricEntry.SOURCE_ADMIN,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("dairymetrics_entry"),
            {
                "department": self.department.id,
                "entry_date": "2026-03-09",
                "approach_count": 6,
                "communication_count": 2,
                "support_amount": 2000,
                "cs_count": 1,
                "refugee_count": 0,
                "submit_action": "save",
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard") + "?saved=1")
        entry.refresh_from_db()
        self.assertEqual(entry.input_source, MemberDailyMetricEntry.SOURCE_MEMBER)

    def test_entry_form_shows_close_activity_button(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_entry"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "保存する")
        self.assertContains(response, "活動終了")
        self.assertNotContains(response, "ダッシュボードへ戻る")

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
        today = timezone.localdate()
        second_department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=second_department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=second_department,
            entry_date=today,
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
        self.assertIn('data-department-select', payload["card_html"])
        self.assertIn('value="7"', payload["form_html"])
        self.assertIn("今日", payload["card_html"])

    def test_dashboard_defaults_to_member_default_department(self):
        un_department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=un_department)
        self.member.default_department = un_department
        self.member.save(update_fields=["default_department"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>UN<', html=False)
        self.assertContains(response, 'value="UN" selected', html=False)

    def test_member_monthly_overview_defaults_to_member_default_department(self):
        un_department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=un_department)
        self.member.default_department = un_department
        self.member.save(update_fields=["default_department"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_member_monthly_overview"), {"month": "2026-03"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="UN" selected', html=False)

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
        self.assertIn("dairymetrics-native-date", form.fields["entry_date"].widget.attrs.get("class", ""))
        self.assertIn("dairymetrics-date-input", form.fields["entry_date"].widget.attrs.get("class", ""))
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
            month=date(2026, 2, 1),
            name="第4路程",
            status="finished",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 7),
        )
        Period.objects.create(
            month=date(2026, 2, 1),
            name="第5路程",
            status="finished",
            start_date=date(2026, 2, 8),
            end_date=date(2026, 2, 15),
        )
        Period.objects.create(
            month=date(2026, 2, 1),
            name="第6路程",
            status="finished",
            start_date=date(2026, 2, 16),
            end_date=date(2026, 2, 28),
        )
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
        self.assertContains(response, "CS/難民 ベスト")
        self.assertContains(response, "金額 ベスト")
        self.assertContains(response, ">アプローチ<")
        self.assertContains(response, ">コミュ率<")
        self.assertContains(response, ">コミュニケーション<")
        self.assertContains(response, ">参加率<")
        self.assertContains(response, ">平均支援額<")
        self.assertNotContains(response, "活動中")
        self.assertContains(response, "fa-arrow-trend-up")
        self.assertContains(response, "fa-arrow-trend-down")
        self.assertContains(response, "+100.0%")
        self.assertContains(response, "過去4路程の推移")
        self.assertContains(response, "第4路程")
        self.assertContains(response, "第1路程")
        self.assertContains(response, "3/5")
        self.assertContains(response, "2,500")

    def test_dashboard_period_scope_uses_member_period_target(self):
        period = Period.objects.create(
            month=date(2026, 3, 1),
            name="第1路程",
            status="active",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 15),
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=period,
            target_count=5,
            target_amount=10000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 5),
            support_amount=4000,
            cs_count=2,
            refugee_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "period"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3/5")
        self.assertContains(response, "4,000/10,000")
        self.assertContains(response, "目標を編集")

    def test_member_can_save_period_target(self):
        period = Period.objects.create(
            month=date(2026, 3, 1),
            name="第1路程",
            status="active",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 15),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("dairymetrics_scope_target") + "?department=WV&scope=period",
            {
                "department": self.department.id,
                "target_count": 7,
                "target_amount": 15000,
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard") + "?department=WV&scope=period&saved=1")
        target = MemberPeriodMetricTarget.objects.get(period=period)
        self.assertEqual(target.target_count, 7)
        self.assertEqual(target.target_amount, 15000)

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
        self.assertNotContains(lifetime_response, "過去7日の推移")
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
        self.assertNotContains(filtered_response, "過去7日の推移")

    def test_dashboard_month_scope_uses_six_month_trend(self):
        for month_offset, month_value in enumerate([10, 11, 12, 1, 2, 3], start=0):
            year = 2025 if month_value >= 10 else 2026
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=date(year, month_value, 5),
                approach_count=month_offset + 1,
                communication_count=month_offset + 1,
                support_amount=(month_offset + 1) * 1000,
                cs_count=month_offset + 1,
            )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "month"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "過去6か月の推移")
        self.assertContains(response, "25/10")
        self.assertContains(response, "26/3")
        self.assertNotContains(response, "過去7日の推移")

    def test_dashboard_month_scope_uses_member_month_target(self):
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=date(2026, 3, 1),
            target_count=10,
            target_amount=20000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 5),
            support_amount=6000,
            cs_count=4,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "month"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4/10")
        self.assertContains(response, "6,000/20,000")
        self.assertContains(response, "目標を編集")

    def test_dashboard_navigation_includes_transaction_entry_link(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "決済入力")
        self.assertContains(response, reverse("dairymetrics_entry_v2_transaction_demo"))

    def test_dashboard_month_goal_card_uses_dairymetrics_actuals_only(self):
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=date(2026, 3, 1),
            target_count=10,
            target_amount=20000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 5),
            support_amount=9000,
            cs_count=5,
            refugee_count=1,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"), {"scope": "month"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "6/10")
        self.assertContains(response, "9,000/20,000")
        self.assertContains(response, "残り 4")
        self.assertContains(response, "残り 11,000")

    def test_member_index_lists_inactive_members(self):
        inactive_member = Member.objects.create(name="Inactive Member", is_active=False)
        MemberDepartment.objects.create(member=inactive_member, department=self.department)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_member_index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "メンバーデータ")
        self.assertContains(response, "Inactive Member")
        self.assertContains(response, "非アクティブ")
        self.assertContains(response, reverse("dairymetrics_member_dashboard", args=[inactive_member.id]))
        self.assertContains(response, 'data-member-switch')
        self.assertContains(response, 'data-member-filter-value="WV"')
        self.assertNotContains(response, 'data-member-filter-value="UN"')
        self.assertContains(response, 'data-department-codes="WV"')

    def test_member_index_uses_department_display_name_for_filter_tags(self):
        style_department = Department.objects.create(code="STYLE1", name="スタイル1")
        style_member = Member.objects.create(name="Style Member")
        MemberDepartment.objects.create(member=style_member, department=style_department)
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_member_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-member-filter-value="STYLE1"', html=False)
        self.assertContains(response, ">スタイル1<", html=False)
        self.assertNotContains(response, ">STYLE1<", html=False)
        self.assertContains(response, 'data-member-filter-select', html=False)

    def test_member_index_defaults_filter_to_un_when_available(self):
        un_department = Department.objects.create(code="UN", name="UN")
        un_member = Member.objects.create(name="UN Member")
        MemberDepartment.objects.create(member=un_member, department=un_department)
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_member_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-member-filter-value="UN" aria-pressed="true"', html=False)
        self.assertContains(response, '<option value="UN" selected>UN</option>', html=False)

    def test_member_dashboard_ajax_switches_selected_member(self):
        inactive_member = Member.objects.create(name="Inactive Member", is_active=False)
        MemberDepartment.objects.create(member=inactive_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=7,
            communication_count=5,
            support_amount=3500,
            cs_count=2,
            refugee_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[inactive_member.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Member Twoさんでログイン中", payload["page_subtitle"])
        self.assertEqual(payload["viewed_member_name"], "Inactive Member")
        self.assertIn("3,500", payload["card_html"])

    def test_member_dashboard_ajax_supports_month_scope(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=7,
            communication_count=5,
            support_amount=3500,
            cs_count=2,
            refugee_count=1,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[self.member.id]),
            {"scope": "month"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(f"今月: {today.strftime('%Y/%m')}", payload["card_html"])
        self.assertIn('?department=WV&scope=month', payload["card_html"])

    def test_member_dashboard_ajax_supports_period_scope_for_un(self):
        today = timezone.localdate()
        un_department = Department.objects.create(code="UN", name="UN")
        target_user = get_user_model().objects.create_user(username="member-un", password="pass123")
        target_member = Member.objects.create(name="UN Member", user=target_user)
        MemberDepartment.objects.create(member=target_member, department=un_department)
        Period.objects.create(
            name="第1路程",
            month=today.replace(day=1),
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        MemberDailyMetricEntry.objects.create(
            member=target_member,
            department=un_department,
            entry_date=today,
            approach_count=7,
            communication_count=5,
            result_count=3,
            support_amount=3500,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[target_member.id]),
            {"department": "UN", "scope": "period"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("今路程: 第1路程", payload["card_html"])
        self.assertIn('?department=UN&scope=period', payload["card_html"])

    def test_member_dashboard_is_readonly_and_allows_inactive_member(self):
        today = timezone.localdate()
        inactive_member = Member.objects.create(name="Inactive Member", is_active=False)
        MemberDepartment.objects.create(member=inactive_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=today,
            approach_count=7,
            communication_count=5,
            support_amount=3500,
            cs_count=2,
            refugee_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=4,
            communication_count=3,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_member_dashboard", args=[inactive_member.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Member Twoさんでログイン中")
        self.assertContains(response, "表示中: Inactive Member")
        self.assertContains(response, "7")
        self.assertContains(response, "3,500")
        self.assertContains(response, 'data-member-filter-value="WV"', html=False)
        self.assertNotContains(response, "入力する")
        self.assertNotContains(response, "スコアを見る")
        self.assertNotContains(response, "目標を設定")
        self.assertNotContains(response, "dairymetrics-open-entry")
        self.assertNotContains(response, "メンバー一覧へ戻る")
        self.assertContains(response, "自分と比較")
        self.assertContains(response, "Inactive MemberさんとMember Twoさんの差分")

    def test_member_dashboard_readonly_month_scope_shows_self_comparison(self):
        today = timezone.localdate()
        inactive_member = Member.objects.create(name="Month Compare Member", is_active=False)
        MemberDepartment.objects.create(member=inactive_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=today,
            support_amount=4000,
            cs_count=2,
            refugee_count=0,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            support_amount=1000,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[inactive_member.id]),
            {"scope": "month"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "自分と比較")
        self.assertContains(response, "+3,000")
        self.assertContains(response, "+300.00%")
        self.assertContains(response, 'data-scope-select', html=False)

    def test_member_dashboard_readonly_period_scope_shows_self_comparison(self):
        today = timezone.localdate()
        inactive_member = Member.objects.create(name="Period Compare Member", is_active=False)
        MemberDepartment.objects.create(member=inactive_member, department=self.department)
        Period.objects.create(
            name="第1路程",
            month=today.replace(day=1),
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=today,
            support_amount=2400,
            cs_count=2,
            refugee_count=0,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            support_amount=1200,
            cs_count=1,
            refugee_count=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[inactive_member.id]),
            {"scope": "period"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "自分と比較")
        self.assertContains(response, "+1,200")
        self.assertContains(response, "+100.00%")

    def test_member_dashboard_allows_scope_switch_links(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=7,
            communication_count=5,
            support_amount=3500,
            cs_count=2,
            refugee_count=1,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_dashboard", args=[self.member.id]),
            {"scope": "month"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '?department=WV&scope=month', html=False)
        self.assertContains(response, 'dairymetrics-scope-tab is-active', html=False)
        self.assertContains(response, "今月")

    def test_member_monthly_overview_shows_month_sheet(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=7,
            communication_count=5,
            cs_count=2,
            refugee_count=1,
            support_amount=3500,
            location_name="Shibuya",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_monthly_overview"),
            {"month": "2026-03", "department": "WV"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月次確認シート")
        self.assertContains(response, "現場実績")
        self.assertContains(response, "戻り実績")
        self.assertContains(response, "Member Two")
        self.assertContains(response, "Shibuya")
        self.assertContains(response, "CS")
        self.assertContains(response, "難民")

    def test_member_overview_shows_admin_like_cards(self):
        today = timezone.localdate()
        teammate_user = get_user_model().objects.create_user(username="member2c", password="pass123")
        teammate = Member.objects.create(name="Member Teammate", user=teammate_user)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        un_department = Department.objects.create(code="UN", name="UN")
        other_user = get_user_model().objects.create_user(username="member2d", password="pass123")
        other_member = Member.objects.create(name="Other Department", user=other_user)
        MemberDepartment.objects.create(member=other_member, department=un_department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=7,
            communication_count=5,
            cs_count=2,
            refugee_count=1,
            support_amount=3500,
            location_name="Shibuya",
            activity_closed=False,
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            approach_count=4,
            communication_count=3,
            cs_count=1,
            refugee_count=0,
            support_amount=1200,
            location_name="Yokohama",
            activity_closed=True,
        )
        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=un_department,
            entry_date=today,
            approach_count=3,
            communication_count=2,
            result_count=1,
            support_amount=2000,
            location_name="Ueno",
            activity_closed=False,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_member_overview"), {"department": "WV"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "活動状況")
        self.assertContains(response, "今日の活動状況")
        self.assertContains(response, "本日の実績")
        self.assertContains(response, "メンバー実績状況")
        self.assertContains(response, "Shibuya")
        self.assertContains(response, "Yokohama")
        self.assertContains(response, "Member Two")
        self.assertContains(response, "Member Teammate")
        self.assertContains(response, "活動中")
        self.assertContains(response, "活動終了")
        self.assertContains(response, "4,700")
        self.assertNotContains(response, "月次シート")
        self.assertContains(response, '<option value="UN"', html=False)
        self.assertNotContains(response, "Other Department")

        other_response = self.client.get(reverse("dairymetrics_member_overview"), {"department": "UN"})

        self.assertEqual(other_response.status_code, 200)
        self.assertContains(other_response, "Other Department")
        self.assertContains(other_response, "Ueno")
        self.assertNotContains(other_response, "Member Teammate")

    def test_member_overview_defaults_to_member_default_department(self):
        un_department = Department.objects.create(code="UN", name="UN")
        other_user = get_user_model().objects.create_user(username="member2default", password="pass123")
        other_member = Member.objects.create(name="Other Department", user=other_user)
        MemberDepartment.objects.create(member=other_member, department=un_department)
        MemberDepartment.objects.create(member=self.member, department=un_department)
        self.member.default_department = un_department
        self.member.save(update_fields=["default_department"])

        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=un_department,
            entry_date=timezone.localdate(),
            result_count=1,
            support_amount=1000,
            location_name="Ueno",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_member_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="UN" selected', html=False)
        self.assertContains(response, "Other Department")

    def test_dashboard_nav_links_to_member_overview(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("dairymetrics_member_overview"))

    def test_member_monthly_overview_adjustment_tab_shows_return_metrics(self):
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="postal",
            return_postal_count=2,
            return_postal_amount=3000,
            return_qr_count=1,
            return_qr_amount=800,
            location_name="新宿",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dairymetrics_member_monthly_overview"),
            {"month": "2026-03", "department": "WV", "tab": "adjustment"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "郵送件数")
        self.assertContains(response, "郵送金額")
        self.assertContains(response, "QR件数")
        self.assertContains(response, "QR金額")
        self.assertContains(response, "3,000")
        self.assertContains(response, "800")
        self.assertContains(response, "現場")
        self.assertContains(response, "新宿")


class DairyMetricsAdminTests(AppTestMixin, TestCase):
    DEFAULT_PASSWORD = "pass123"

    def setUp(self):
        self.admin = self.create_user("admin_user", password="pass123", is_staff=True)
        self.department = self.create_department("UN")
        self.department_wv = self.create_department("WV")
        self.member = self.create_member(name="Member Three", department=self.department)
        self.member_wv = self.create_member(name="Member Four", department=self.department_wv)

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
        self.assertRedirects(response, reverse("dairymetrics_admin_monthly_overview") + "?month=2026-03")
        adjustment = MetricAdjustment.objects.get()
        self.assertEqual(adjustment.created_by, self.admin)
        self.assertEqual(adjustment.source_type, "postal")

    def test_adjustment_form_uses_japanese_labels(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dairymetrics_adjustment_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "メンバー")
        self.assertContains(response, "部署")
        self.assertContains(response, "対象日")
        self.assertContains(response, "種別")
        self.assertContains(response, "郵送件数")
        self.assertContains(response, "郵送金額")
        self.assertContains(response, "QR件数")
        self.assertContains(response, "QR金額")

    def test_admin_monthly_overview_requires_staff(self):
        response = self.client.get(reverse("dairymetrics_admin_monthly_overview"))
        self.assertRedirects(response, reverse("dairymetrics_login"))

    def test_admin_member_dashboard_keeps_admin_viewer_context(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=1,
            support_amount=1200,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dairymetrics_member_dashboard", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "管理者としてメンバーデータを閲覧中")
        self.assertContains(response, "表示中: Member Three")
        self.assertNotContains(response, "Member Threeさんのダッシュボード")
        self.assertNotContains(response, '>ダッシュボード<', html=False)
        self.assertNotContains(response, ">活動状況<", html=False)
        self.assertNotContains(response, ">スコア<", html=False)

    def test_admin_compare_redirects_to_admin_overview(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dairymetrics_compare"))

        self.assertRedirects(response, reverse("dairymetrics_admin_overview"))

    def test_admin_ranking_overview_shows_today_rankings(self):
        today = timezone.localdate()
        teammate = Member.objects.create(name="Ranking Partner")
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=3,
            communication_count=2,
            result_count=1,
            support_amount=900,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=today,
            approach_count=6,
            communication_count=4,
            result_count=2,
            support_amount=2500,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dairymetrics_admin_ranking_overview"), {"department": "UN"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全体ランキング")
        self.assertContains(response, "件数")
        self.assertContains(response, "Ranking Partner")
        self.assertContains(response, "Member Three")
        self.assertContains(response, '?department=UN&scope=month', html=False)

    def test_admin_ranking_overview_defaults_to_un_department(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=900,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member_wv,
            department=self.department_wv,
            entry_date=today,
            cs_count=1,
            support_amount=1200,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dairymetrics_admin_ranking_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN 全体ランキング")

    def test_admin_ranking_overview_supports_month_scope(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=3,
            communication_count=2,
            result_count=1,
            support_amount=900,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 10),
            source_type="postal",
            return_postal_count=1,
            return_postal_amount=500,
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_admin_ranking_overview"),
            {"department": "UN", "scope": "month"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "今月")
        self.assertContains(response, "1,400")

    def test_admin_overview_shows_activity_cards_without_submission_summary(self):
        today = timezone.localdate()
        active_member = Member.objects.create(name="Member Active")
        late_member = Member.objects.create(name="Member Late")
        low_member = Member.objects.create(name="Member Low")
        MemberDepartment.objects.create(member=active_member, department=self.department)
        MemberDepartment.objects.create(member=late_member, department=self.department)
        MemberDepartment.objects.create(member=low_member, department=self.department)
        active_entry = MemberDailyMetricEntry.objects.create(
            member=active_member,
            department=self.department,
            entry_date=today,
            approach_count=2,
            communication_count=1,
            result_count=1,
            support_amount=1500,
            location_name="Shibuya",
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        closed_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=1,
            communication_count=1,
            result_count=1,
            support_amount=1000,
            location_name="Ikebukuro",
            activity_closed=True,
            activity_closed_at=timezone.now(),
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        MemberDailyMetricEntry.objects.create(
            member=late_member,
            department=self.department,
            entry_date=today,
            approach_count=4,
            communication_count=2,
            result_count=2,
            support_amount=2400,
            location_name="Ueno",
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        MemberDailyMetricEntry.objects.create(
            member=low_member,
            department=self.department,
            entry_date=today,
            approach_count=1,
            communication_count=1,
            result_count=0,
            support_amount=500,
            location_name="Akabane",
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        now = timezone.now()
        MemberDailyMetricEntry.objects.filter(pk=active_entry.pk).update(updated_at=now)
        MemberDailyMetricEntry.objects.filter(pk=closed_entry.pk).update(updated_at=now - timedelta(minutes=10))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dairymetrics_admin_overview"), {"department": "UN"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "活動中")
        self.assertContains(response, "活動終了")
        self.assertContains(response, "本日の実績")
        self.assertContains(response, "メンバー実績状況")
        self.assertContains(response, "今日のランキング")
        self.assertContains(response, "件数")
        self.assertContains(response, "金額")
        self.assertContains(response, "アプローチ数")
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "コミュニケーション数")
        self.assertContains(response, "参加率")
        self.assertContains(response, "平均支援額")
        self.assertContains(response, "Member Active")
        self.assertContains(response, "Member Late")
        self.assertContains(response, "Member Low")
        self.assertContains(response, "Member Three")
        self.assertContains(response, "Shibuya")
        self.assertContains(response, "Ikebukuro")
        self.assertContains(response, '<span class="dairymetrics-rank-badge">4</span>', html=False)
        self.assertNotContains(response, "提出対象")
        self.assertNotContains(response, "提出済み")
        self.assertNotContains(response, "管理メニュー")
        self.assertContains(response, reverse("dairymetrics_member_dashboard", args=[self.member.id]))
        self.assertLess(response.content.decode().find("Member Active"), response.content.decode().find("Member Three"))
        self.assertLess(response.content.decode().find("メンバー実績状況"), response.content.decode().find("今日のランキング"))

    def test_admin_overview_filters_by_department(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=1200,
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_admin_overview"),
            {"department": "UN"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Member Three")
        self.assertContains(response, "活動中")
        self.assertNotContains(response, "Member Four")

    def test_admin_overview_returns_ajax_partial_when_department_changes(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member_wv,
            department=self.department_wv,
            entry_date=today,
            cs_count=1,
            refugee_count=1,
            support_amount=3000,
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_admin_overview"),
            {"department": "WV"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["department_code"], "WV")
        self.assertIn("overview_html", response.json())
        self.assertIn("Member Four", response.json()["overview_html"])
        self.assertIn("CS", response.json()["overview_html"])
        self.assertIn("難民", response.json()["overview_html"])
        self.assertNotIn("更新</button>", response.json()["overview_html"])

    def test_admin_overview_ignores_admin_created_today_entries_for_activity(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=1200,
            activity_closed=False,
            input_source=MemberDailyMetricEntry.SOURCE_ADMIN,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dairymetrics_admin_overview"), {"department": "UN"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span class="dairymetrics-admin-stat-label">活動中</span>', html=False)
        self.assertContains(response, '<strong class="dairymetrics-admin-stat-value">0</strong>', html=False)
        self.assertContains(response, '<span class="dairymetrics-admin-stat-label">活動終了</span>', html=False)
        self.assertContains(response, "本日更新されたメンバーはいません")

    def test_admin_monthly_overview_shows_month_totals_and_sheet(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            approach_count=5,
            communication_count=3,
            result_count=2,
            support_amount=4000,
            location_name="Shibuya",
            activity_closed=False,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member_wv,
            department=self.department_wv,
            entry_date=today,
            location_name="Shibuya",
            cs_count=1,
            refugee_count=1,
            support_amount=3000,
            activity_closed=True,
            activity_closed_at=timezone.now(),
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": today.strftime("%Y-%m"), "department": "WV"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Member Four")
        self.assertContains(response, "月次実績シート")
        self.assertContains(response, "月合計")
        self.assertContains(response, "月平均")
        self.assertContains(response, "現場実績")
        self.assertContains(response, "戻り実績")
        self.assertContains(response, "AP")
        self.assertContains(response, "CM")
        self.assertContains(response, "CS")
        self.assertContains(response, "難民")
        self.assertContains(response, "現場")
        self.assertContains(response, "Shibuya")
        self.assertContains(response, str(today.day))
        self.assertNotContains(response, "今日の活動状況")
        self.assertNotContains(response, "未入力")
        self.assertNotContains(response, "月次合計")

    def test_admin_monthly_overview_renders_excel_like_daily_cells(self):
        target_month = date(2026, 3, 1)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=5,
            communication_count=3,
            result_count=2,
            support_amount=4000,
            location_name="Shibuya",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 10),
            source_type="postal",
            result_count=1,
            support_amount=1200,
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": target_month.strftime("%Y-%m"), "department": "UN"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Member Three")
        self.assertContains(response, "2")
        self.assertContains(response, "4,000")
        self.assertContains(response, "Shibuya")
        self.assertContains(response, "dairymetrics-admin-month-sheet")
        self.assertContains(response, "data-monthly-header-scroll", html=False)
        self.assertContains(response, "data-monthly-right-body", html=False)
        self.assertNotContains(response, "1,200")
        self.assertNotContains(response, "data-day-count-label")

    def test_admin_monthly_overview_adjustment_tab_shows_only_return_metrics(self):
        target_month = date(2026, 3, 1)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=2,
            support_amount=4000,
            location_name="Shibuya",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 10),
            source_type="postal",
            result_count=1,
            support_amount=1200,
            return_postal_count=2,
            return_postal_amount=5000,
            return_qr_count=1,
            return_qr_amount=800,
            location_name="Shibuya",
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": target_month.strftime("%Y-%m"), "department": "UN", "tab": "adjustment"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "郵送件数")
        self.assertContains(response, "郵送金額")
        self.assertContains(response, "QR件数")
        self.assertContains(response, "QR金額")
        self.assertContains(response, "5,000")
        self.assertContains(response, "800")
        self.assertContains(response, "現場")
        self.assertContains(response, "Shibuya")
        self.assertNotContains(response, ">AP<", html=False)
        self.assertNotContains(response, ">CM<", html=False)
        self.assertNotContains(response, ">件数<", html=False)
        self.assertNotContains(response, ">金額<", html=False)

    def test_admin_monthly_update_cell_updates_numeric_field_entry(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=2,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": entry.entry_date.strftime("%Y-%m-%d"),
                "field": "result_count",
                "value": "5",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.result_count, 5)
        self.assertEqual(entry.input_source, MemberDailyMetricEntry.SOURCE_MEMBER)

    def test_admin_monthly_update_cell_creates_admin_sourced_entry(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "result_count",
                "value": "5",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        entry = MemberDailyMetricEntry.objects.get(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
        )
        self.assertEqual(entry.input_source, MemberDailyMetricEntry.SOURCE_ADMIN)

    def test_admin_monthly_update_cell_skips_empty_zero_create(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "result_count",
                "value": "0",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            MemberDailyMetricEntry.objects.filter(
                member=self.member,
                department=self.department,
                entry_date=date(2026, 3, 9),
            ).exists()
        )

    def test_admin_monthly_overview_uses_result_count_field_for_un_count_cells(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=2,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": "2026-03", "department": self.department.code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-field="result_count"', html=False)
        self.assertNotContains(response, 'data-field="count_value"', html=False)

    def test_admin_monthly_overview_defaults_to_activity_day_sort(self):
        other_member = Member.objects.create(name="Member Alpha")
        MemberDepartment.objects.create(member=other_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 10),
            result_count=1,
        )
        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=5,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": "2026-03", "department": "UN"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.find("Member Three"), content.find("Member Alpha"))

    def test_admin_monthly_overview_can_sort_by_amount(self):
        other_member = Member.objects.create(name="Member Alpha")
        MemberDepartment.objects.create(member=other_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            support_amount=1000,
        )
        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            support_amount=5000,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": "2026-03", "department": "UN", "sort": "amount"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.find("Member Alpha"), content.find("Member Three"))

    def test_admin_monthly_update_cell_updates_location_name(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            location_name="Shibuya",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "location_name",
                "value": "Ikebukuro",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            MemberDailyMetricEntry.objects.get(member=self.member, department=self.department, entry_date=date(2026, 3, 9)).location_name,
            "Ikebukuro",
        )

    def test_admin_monthly_update_cell_creates_adjustment_for_return_field(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "return_postal_count",
                "value": "2",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        adjustment = MetricAdjustment.objects.get(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="other",
            note="__inline_monthly_adjustment__",
        )
        self.assertEqual(adjustment.return_postal_count, 2)

    def test_admin_monthly_update_cell_adjustment_field_preserves_existing_total(self):
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="postal",
            return_postal_count=1,
            return_postal_amount=500,
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "return_postal_count",
                "value": "3",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        inline_adjustment = MetricAdjustment.objects.get(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="other",
            note="__inline_monthly_adjustment__",
        )
        self.assertEqual(inline_adjustment.return_postal_count, 2)

    def test_admin_monthly_update_cell_updates_wv_counts(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member_wv,
            department=self.department_wv,
            entry_date=date(2026, 3, 9),
            cs_count=1,
            refugee_count=2,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member_wv.id,
                "department": self.department_wv.code,
                "entry_date": entry.entry_date.strftime("%Y-%m-%d"),
                "field": "cs_count",
                "value": "4",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.cs_count, 4)
        self.assertEqual(entry.refugee_count, 2)

    def test_admin_monthly_bulk_update_updates_existing_and_creates_new_entry(self):
        existing_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=2,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_bulk_update"),
            data=json.dumps(
                {
                    "changes": [
                        {
                            "member_id": self.member.id,
                            "department": self.department.code,
                            "entry_date": "2026-03-09",
                            "field": "result_count",
                            "value": "5",
                        },
                        {
                            "member_id": self.member.id,
                            "department": self.department.code,
                            "entry_date": "2026-03-10",
                            "field": "approach_count",
                            "value": "9",
                        },
                    ]
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        existing_entry.refresh_from_db()
        self.assertEqual(existing_entry.result_count, 5)
        self.assertEqual(existing_entry.input_source, MemberDailyMetricEntry.SOURCE_MEMBER)
        created_entry = MemberDailyMetricEntry.objects.get(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 10),
        )
        self.assertEqual(created_entry.approach_count, 9)
        self.assertEqual(created_entry.input_source, MemberDailyMetricEntry.SOURCE_ADMIN)
        self.assertEqual(response.json()["updated_count"], 2)

    def test_admin_monthly_bulk_update_keeps_target_member_when_sorted(self):
        other_member = Member.objects.create(name="Member Alpha")
        MemberDepartment.objects.create(member=other_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            support_amount=1000,
            result_count=1,
        )
        other_entry = MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            support_amount=5000,
            result_count=2,
        )
        self.client.force_login(self.admin)

        page_response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": "2026-03", "department": "UN", "sort": "amount"},
        )
        self.assertEqual(page_response.status_code, 200)
        content = page_response.content.decode()
        self.assertLess(content.find("Member Alpha"), content.find("Member Three"))

        save_response = self.client.post(
            reverse("dairymetrics_admin_monthly_bulk_update"),
            data=json.dumps(
                {
                    "changes": [
                        {
                            "member_id": self.member.id,
                            "department": self.department.code,
                            "entry_date": "2026-03-09",
                            "field": "result_count",
                            "value": "7",
                        }
                    ]
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(
            MemberDailyMetricEntry.objects.get(
                member=self.member,
                department=self.department,
                entry_date=date(2026, 3, 9),
            ).result_count,
            7,
        )
        other_entry.refresh_from_db()
        self.assertEqual(other_entry.result_count, 2)

    def test_admin_monthly_bulk_update_updates_adjustment_totals(self):
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="postal",
            return_postal_count=1,
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_bulk_update"),
            data=json.dumps(
                {
                    "changes": [
                        {
                            "member_id": self.member.id,
                            "department": self.department.code,
                            "entry_date": "2026-03-09",
                            "field": "return_postal_count",
                            "value": "4",
                        }
                    ]
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        inline_adjustment = MetricAdjustment.objects.get(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="other",
            note="__inline_monthly_adjustment__",
        )
        self.assertEqual(inline_adjustment.return_postal_count, 3)

    def test_admin_monthly_bulk_update_rejects_invalid_value(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_bulk_update"),
            data=json.dumps(
                {
                    "changes": [
                        {
                            "member_id": self.member.id,
                            "department": self.department.code,
                            "entry_date": "2026-03-09",
                            "field": "result_count",
                            "value": "-1",
                        }
                    ]
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_value")
        self.assertEqual(response.json()["index"], 0)

    def test_admin_monthly_bulk_update_skips_zero_only_changes_without_creating_entries(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_bulk_update"),
            data=json.dumps(
                {
                    "changes": [
                        {
                            "member_id": self.member.id,
                            "department": self.department.code,
                            "entry_date": "2026-03-09",
                            "field": "result_count",
                            "value": "0",
                        }
                    ]
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            MemberDailyMetricEntry.objects.filter(
                member=self.member,
                department=self.department,
                entry_date=date(2026, 3, 9),
            ).exists()
        )

    def test_admin_monthly_update_cell_rejects_negative_values(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "result_count",
                "value": "-1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_value")

    def test_admin_monthly_update_cell_rejects_adjustment_value_below_existing_total(self):
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="postal",
            return_postal_count=3,
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "return_postal_count",
                "value": "2",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "value_below_existing_adjustments")

    def test_admin_monthly_overview_reflects_updated_entry_value(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=2,
            support_amount=1000,
        )
        self.client.force_login(self.admin)

        save_response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "result_count",
                "value": "5",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(save_response.status_code, 200)

        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": "2026-03", "department": "UN"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">5<", html=False)

    def test_admin_monthly_adjustment_tab_reflects_updated_return_total(self):
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type="postal",
            return_postal_count=1,
            return_postal_amount=500,
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        save_response = self.client.post(
            reverse("dairymetrics_admin_monthly_update_cell"),
            {
                "member_id": self.member.id,
                "department": self.department.code,
                "entry_date": "2026-03-09",
                "field": "return_postal_count",
                "value": "4",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(save_response.status_code, 200)

        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": "2026-03", "department": "UN", "tab": "adjustment"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">4<", html=False)

    def test_admin_monthly_overview_filters_by_department(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            result_count=1,
            support_amount=1200,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member_wv,
            department=self.department_wv,
            entry_date=date(2026, 3, 9),
            cs_count=2,
            refugee_count=1,
            support_amount=2500,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_admin_monthly_overview"),
            {"month": "2026-03", "department": "UN"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Member Three")
        self.assertNotContains(response, "Member Four")

    def test_admin_monthly_comparison_requires_staff(self):
        response = self.client.get(reverse("dairymetrics_admin_monthly_comparison"))
        self.assertRedirects(response, reverse("dairymetrics_login"))

    def test_admin_monthly_comparison_shows_previous_month_diff_sheet(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 2, 10),
            approach_count=4,
            communication_count=2,
            result_count=1,
            support_amount=2000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 10),
            approach_count=6,
            communication_count=3,
            result_count=2,
            support_amount=3500,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 2, 10),
            source_type="postal",
            return_postal_count=1,
            return_postal_amount=500,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 10),
            source_type="other",
            return_qr_count=2,
            return_qr_amount=1200,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_admin_monthly_comparison"),
            {"month": "2026-03", "compare_month": "2026-02", "department": "UN"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月比較シート")
        self.assertContains(response, "2026/02")
        self.assertContains(response, "2026/03")
        self.assertContains(response, "差分")
        self.assertContains(response, "増減率")
        self.assertContains(response, "Member Three")
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "参加率")
        self.assertContains(response, "平均支援額")
        self.assertContains(response, "郵送戻り")
        self.assertContains(response, "QR戻り")
        self.assertContains(response, "+2")
        self.assertContains(response, "+16.70%")
        self.assertContains(response, "+50.00%")

    def test_admin_monthly_comparison_splits_wv_cs_and_refugee_rows(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member_wv,
            department=self.department_wv,
            entry_date=date(2026, 2, 9),
            approach_count=4,
            communication_count=2,
            cs_count=1,
            refugee_count=3,
            support_amount=2000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member_wv,
            department=self.department_wv,
            entry_date=date(2026, 3, 9),
            approach_count=6,
            communication_count=3,
            cs_count=3,
            refugee_count=1,
            support_amount=2600,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_admin_monthly_comparison"),
            {"month": "2026-03", "compare_month": "2026-02", "department": "WV"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Member Four")
        self.assertContains(response, "CS")
        self.assertContains(response, "難民")
        self.assertNotContains(response, "件数")
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "参加率")
        self.assertContains(response, "+2")
        self.assertContains(response, "+50.00%")

    def test_admin_monthly_comparison_handles_empty_rate_values(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 10),
            support_amount=1000,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_admin_monthly_comparison"),
            {"month": "2026-03", "compare_month": "2026-02", "department": "UN"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "参加率")

    def test_admin_monthly_comparison_defaults_compare_month_to_previous_month(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 2, 10),
            support_amount=1000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 10),
            support_amount=2000,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_admin_monthly_comparison"),
            {"month": "2026-03", "department": "UN"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="compare_month" value="2026-02"', html=False)


class DairyMetricsV2DemoTests(AppTestMixin, TestCase):
    DEFAULT_PASSWORD = "pass123"

    def setUp(self):
        self.department = self.create_department("UN")
        self.user, self.member = self.create_member_user(
            username="metrics_member",
            password="pass123",
            name="石井",
            department=self.department,
        )
        self.admin = self.create_user("metrics_admin", password="pass123", is_staff=True)
        self.teammate = self.create_member(name="片山", department=self.department)
        self.amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
        )
        today = timezone.localdate()
        self.period = Period.objects.create(
            month=today.replace(day=1),
            name="第1次路程",
            status=TARGET_STATUS_ACTIVE,
            start_date=today - timedelta(days=14),
            end_date=today + timedelta(days=7),
        )
        MonthTargetMetricValue.objects.create(
            department=self.department,
            target_month=today.replace(day=1),
            metric=self.amount_metric,
            value=50000,
        )
        PeriodTargetMetricValue.objects.create(
            department=self.department,
            period=self.period,
            metric=self.amount_metric,
            value=30000,
        )
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=20000,
            target_count=10,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=self.period,
            target_amount=15000,
            target_count=8,
        )
        entry_one = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=2),
            approach_count=12,
            communication_count=6,
            result_count=2,
            support_amount=6000,
            daily_target_amount=5000,
        )
        MemberMetricTransaction.objects.create(
            entry=entry_one,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_OVERSEAS,
            location="渋谷",
            comment="A",
        )
        MemberMetricTransaction.objects.create(
            entry=entry_one,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="B",
        )
        entry_two = MemberDailyMetricEntry.objects.create(
            member=self.teammate,
            department=self.department,
            entry_date=today - timedelta(days=1),
            approach_count=8,
            communication_count=4,
            result_count=1,
            support_amount=2000,
            daily_target_amount=4000,
        )
        MemberMetricTransaction.objects.create(
            entry=entry_two,
            support_amount=2000,
            age_band=MemberMetricTransaction.AGE_BAND_FORTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="新宿",
            comment="C",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today - timedelta(days=1),
            source_type=MetricAdjustment.SOURCE_INCREASE,
            result_count=1,
            support_amount=1000,
            location_name="池袋",
        )
        MetricAdjustment.objects.create(
            member=self.teammate,
            department=self.department,
            target_date=today - timedelta(days=1),
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=500,
            location_name="新宿戻り",
        )

    def test_metrics_v2_demo_requires_login(self):
        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"))
        self.assertRedirects(response, reverse("performance_login"))

    def test_metrics_v2_demo_renders_member_sections(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "分析する")
        self.assertContains(response, "集計条件")
        self.assertContains(response, "月ごとの比較・推移")
        self.assertContains(response, "路程ごとの比較・推移")
        self.assertContains(response, "ランキングモード")
        self.assertContains(response, "年代別決済比率")
        self.assertContains(response, "metrics-v2-dashboard-data")
        self.assertContains(response, reverse("performance_member_dashboard"))
        self.assertContains(response, "実績管理ダッシュボード")
        self.assertContains(response, "決済入力")
        self.assertContains(response, "過去の実績を見る")
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, reverse("dairymetrics_metrics_report"))
        self.assertNotContains(response, "現行 Metrics")
        self.assertNotContains(response, "総合管理者ページ")
        personal_average_values = {
            item["label"]: item["value"] for item in response.context["metrics_v2_payload"]["personal_summary"]["averages"]
        }
        overall_average_values = {
            item["label"]: item["value"] for item in response.context["metrics_v2_payload"]["overall_summary"]["averages"]
        }
        self.assertEqual(personal_average_values["1決済あたりの平均金額"], "3,000円")
        self.assertEqual(overall_average_values["1決済あたりの平均金額"], "2,667円")

    def test_metrics_v2_period_history_excludes_planned_periods(self):
        today = timezone.localdate()
        Period.objects.create(
            month=today.replace(day=1),
            name="予定路程",
            status=TARGET_STATUS_PLANNED,
            start_date=today - timedelta(days=8),
            end_date=today - timedelta(days=4),
        )
        finished_period = Period.objects.create(
            month=today.replace(day=1),
            name="終了路程",
            status=TARGET_STATUS_FINISHED,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=9),
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=finished_period.start_date,
            result_count=1,
            support_amount=3000,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"))

        self.assertEqual(response.status_code, 200)
        labels = response.context["metrics_v2_payload"]["period_history"]["labels"]
        self.assertIn("終了路程", labels)
        self.assertIn(self.period.name, labels)
        self.assertNotIn("予定路程", labels)

    def test_metrics_report_renders_monthly_summary_and_rankings(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()

        response = self.client.get(
            reverse("dairymetrics_metrics_report"),
            {"department": self.department.code, "scope": "month", "month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, "出力条件")
        self.assertContains(response, "目標との差分")
        self.assertContains(response, "補正実績")
        self.assertContains(response, "補正実績一覧")
        self.assertContains(response, "増額件数")
        self.assertContains(response, "増額金額")
        self.assertNotContains(response, "各項目の上位3名")
        self.assertContains(response, "合計支援金額")
        self.assertContains(response, "即決 16,000円 / 補正 1,000円")
        self.assertContains(response, "AP / CM数")
        self.assertContains(response, "1決済当たりの平均")
        self.assertContains(response, "1稼働当たりの平均")
        self.assertContains(response, "最高金額達成日")
        self.assertContains(response, "最低金額達成日")
        self.assertContains(response, f"{today - timedelta(days=2):%Y/%m/%d}")
        self.assertContains(response, f"{today - timedelta(days=1):%Y/%m/%d}")
        self.assertContains(response, "日別推移")
        self.assertContains(response, "メンバー別集計")
        self.assertContains(response, "コミュ率")
        self.assertContains(response, "平均/決済")
        self.assertContains(response, "平均/稼働")
        self.assertContains(response, "属性別分析")
        self.assertContains(response, "年代別決済比率")
        self.assertContains(response, "男女比")
        self.assertContains(response, "国籍比")
        self.assertContains(response, "属性別の平均金額")
        self.assertContains(response, "metrics-v2-dashboard-data")
        self.assertContains(response, "metrics-v2-distribution-chart")
        self.assertContains(response, "2件を見る")
        self.assertContains(response, 'class="metrics-report-daily-card-list', html=False)
        self.assertContains(response, 'class="metrics-report-daily-card"', html=False)
        self.assertContains(response, 'class="metrics-report-transaction-row"', html=False)
        self.assertContains(response, 'colspan="5"', html=False)
        self.assertContains(response, "現場: 渋谷")
        self.assertContains(response, "メモ: A")
        self.assertContains(response, 'data-metrics-report-member-table', html=False)
        self.assertContains(response, 'class="metrics-report-sort-heading"', html=False)
        self.assertContains(response, 'data-sort-index="2"', html=False)
        self.assertContains(response, 'data-sort="13000"', html=False)
        self.assertContains(response, 'data-metrics-report-sortable-table', html=False)
        self.assertContains(response, 'data-sort-index="4"', html=False)
        self.assertContains(response, "増額")
        self.assertContains(response, "池袋")
        self.assertContains(response, "新宿戻り")
        self.assertContains(response, 'data-sort="1000"', html=False)
        self.assertContains(response, 'activeDirection === "desc" ? "asc" : "desc"', html=False)
        self.assertNotContains(response, "metrics-report-sort-btn")
        self.assertContains(response, "17,000円")
        self.assertContains(response, "50,000円")
        self.assertContains(response, "片山")
        self.assertNotContains(response, "印刷 / PDF保存")
        self.assertNotIn("ranking_sections", response.context["report"])
        self.assertEqual(response.context["report"]["summary_cards"][6]["value"], "2,667円")
        self.assertEqual(response.context["report"]["distribution_cards"][0]["total_text"], "3件")
        self.assertEqual(response.context["report"]["average_amount_comparison"]["age"]["labels"], ["20代", "30代", "40代"])
        adjustment_cards = {card["label"]: card["value"] for card in response.context["report"]["adjustment_cards"]}
        self.assertEqual(adjustment_cards["増額件数"], "1")
        self.assertEqual(adjustment_cards["増額金額"], "1,000円")
        adjustment_rows = {row["type_text"]: row for row in response.context["report"]["adjustment_rows"]}
        self.assertEqual(adjustment_rows["増額"]["amount_text"], "1,000円")
        self.assertEqual(adjustment_rows["増額"]["location_text"], "池袋")
        member_rows = {row["member_name"]: row for row in response.context["report"]["member_rows"]}
        self.assertEqual(member_rows[self.member.name]["amount_text"], "13,000")
        self.assertEqual(member_rows[self.member.name]["count_text"], "5")
        self.assertEqual(member_rows[self.member.name]["approach_text"], "12")
        self.assertEqual(member_rows[self.member.name]["communication_text"], "6")
        self.assertEqual(member_rows[self.member.name]["communication_rate_text"], "50.0%")
        self.assertEqual(member_rows[self.member.name]["conversion_rate_text"], "66.7%")
        self.assertEqual(member_rows[self.member.name]["average_amount_per_decision_text"], "3,000")
        self.assertEqual(member_rows[self.member.name]["average_amount_per_active_day_text"], "13,000")
        self.assertEqual(member_rows[self.member.name]["active_days_text"], "1")

    def test_metrics_report_renders_period_scope(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_metrics_report"),
            {"department": self.department.code, "scope": "period", "period_id": self.period.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.period.name)
        self.assertContains(response, f"{self.period.start_date:%Y/%m/%d} - {self.period.end_date:%Y/%m/%d}")
        self.assertContains(response, "30,000円")

    def test_metrics_report_period_options_exclude_planned_periods(self):
        today = timezone.localdate()
        planned_period = Period.objects.create(
            month=today.replace(day=1),
            name="予定路程",
            status=TARGET_STATUS_PLANNED,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=10),
        )

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_metrics_report"),
            {"department": self.department.code, "scope": "period", "period_id": planned_period.id},
        )

        self.assertEqual(response.status_code, 200)
        option_ids = [period.id for period in response.context["period_options"]]
        self.assertNotIn(planned_period.id, option_ids)
        self.assertEqual(response.context["scope"].period.id, self.period.id)
        self.assertNotContains(response, "予定路程")

    def test_metrics_report_renders_wv_breakdowns(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)
        amount_metric = TargetMetric.objects.create(
            department=wv_department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
        )
        today = timezone.localdate()
        MonthTargetMetricValue.objects.create(
            department=wv_department,
            target_month=today.replace(day=1),
            metric=amount_metric,
            value=30000,
        )
        MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=today,
            approach_count=8,
            communication_count=5,
            result_count=2,
            cs_count=2,
            refugee_count=1,
            support_amount=9000,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_metrics_report"),
            {"department": wv_department.code, "scope": "month", "month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CS 2件 / 難民 1件")
        self.assertNotContains(response, "合計 3件 / CS 2件 / 難民 1件")
        self.assertContains(response, "CS件数")
        self.assertContains(response, "難民件数")
        self.assertContains(response, "CS限定の年代別決済比率")
        self.assertContains(response, "CS限定の男女比")
        self.assertContains(response, "CS限定の国籍比")
        self.assertContains(response, 'data-sort-index="1"', html=False)
        self.assertContains(response, 'data-sort-index="2"', html=False)
        self.assertEqual(response.context["report"]["summary_cards"][1]["value"], "CS 2件 / 難民 1件")
        self.assertEqual(response.context["report"]["daily_rows"][0]["cs_count_text"], "2")
        self.assertEqual(response.context["report"]["daily_rows"][0]["refugee_count_text"], "1")
        self.assertEqual(response.context["report"]["member_rows"][0]["cs_count_text"], "2")
        self.assertEqual(response.context["report"]["member_rows"][0]["refugee_count_text"], "1")

    def test_metrics_v2_demo_renders_admin_overall_mode(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"), {"department": self.department.code, "scope": "period", "period_id": self.period.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN の全体分析")
        self.assertContains(response, f"{self.period.start_date:%Y/%m/%d} - {self.period.end_date:%Y/%m/%d}")
        self.assertContains(response, "ランキングモード")
        self.assertContains(response, "属性別の平均金額")
        self.assertContains(response, "管理者用ダッシュボード")
        self.assertContains(response, "過去の実績を見る")
        self.assertContains(response, "総合管理者ページ")
        self.assertNotContains(response, "決済入力")
        self.assertContains(response, reverse("performance_member_insight", args=[self.member.id, self.department.id]))

    def test_metrics_v2_demo_can_render_selected_member_for_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_metrics_v2_demo"),
            {"department": self.department.code, "member": str(self.member.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_member"], self.member)
        self.assertContains(response, f"{self.member.name}さん / {self.department.name} の分析")
        self.assertContains(response, reverse("performance_index"))
        self.assertContains(response, reverse("performance_member_insight", args=[self.member.id, self.department.id]))
        self.assertContains(response, reverse("performance_member_history_insight", args=[self.member.id, self.department.id]))

    def test_metrics_v2_demo_defaults_admin_department_to_un(self):
        other_department = Department.objects.create(code="WV", name="WV")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_department"].code, "UN")
        self.assertContains(
            response,
            f'<option value="{self.department.code}" selected>{self.department.name}</option>',
            html=True,
        )

    def test_metrics_v2_demo_auto_closes_stale_open_entries(self):
        stale_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate() - timedelta(days=1),
            result_count=1,
            support_amount=1000,
            activity_closed=False,
            activity_closed_at=None,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"))

        self.assertEqual(response.status_code, 200)
        stale_entry.refresh_from_db()
        self.assertTrue(stale_entry.activity_closed)
        self.assertIsNotNone(stale_entry.activity_closed_at)

    def test_metrics_v2_demo_recent_period_history_ends_with_current_active_period(self):
        today = timezone.localdate()
        previous_period = Period.objects.create(
            month=(today.replace(day=1) - timedelta(days=1)).replace(day=1),
            name="第0次路程",
            status=TARGET_STATUS_FINISHED,
            start_date=today - timedelta(days=35),
            end_date=today - timedelta(days=15),
        )
        PeriodTargetMetricValue.objects.create(
            department=self.department,
            period=previous_period,
            metric=self.amount_metric,
            value=24000,
        )
        previous_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=20),
            approach_count=10,
            communication_count=5,
            result_count=1,
            support_amount=2500,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=previous_entry,
            support_amount=2500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="池袋",
            comment="old",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"))

        self.assertEqual(response.status_code, 200)
        period_labels = response.context["metrics_v2_payload"]["period_history"]["labels"]
        self.assertEqual(period_labels[-1], self.period.name)
        self.assertIn(previous_period.name, period_labels)

    def test_metrics_v2_demo_shows_wv_count_breakdowns_and_cs_only_distribution_cards(self):
        wv_department = self.create_department("WV")
        wv_user, wv_member = self.create_member_user(
            username="wv_metrics_member",
            password="pass123",
            name="WV石井",
            department=wv_department,
        )
        wv_teammate = self.create_member(name="WV片山", department=wv_department)
        wv_amount_metric = TargetMetric.objects.create(
            department=wv_department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
        )
        today = timezone.localdate()
        MonthTargetMetricValue.objects.create(
            department=wv_department,
            target_month=today.replace(day=1),
            metric=wv_amount_metric,
            value=40000,
        )
        wv_entry_one = MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=today - timedelta(days=2),
            approach_count=10,
            communication_count=5,
        )
        MemberMetricTransaction.objects.create(
            entry=wv_entry_one,
            support_amount=9000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="WV-CS",
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=2,
            wv_refugee_amount=0,
        )
        MemberMetricTransaction.objects.create(
            entry=wv_entry_one,
            support_amount=2000,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_OVERSEAS,
            location="渋谷",
            comment="WV-Refugee",
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_cs_count=0,
            wv_refugee_amount=2000,
        )
        wv_entry_two = MemberDailyMetricEntry.objects.create(
            member=wv_teammate,
            department=wv_department,
            entry_date=today - timedelta(days=1),
            approach_count=8,
            communication_count=4,
        )
        MemberMetricTransaction.objects.create(
            entry=wv_entry_two,
            support_amount=6500,
            age_band=MemberMetricTransaction.AGE_BAND_FORTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="新宿",
            comment="WV-Both",
            wv_result_type=MemberMetricTransaction.WV_RESULT_BOTH,
            wv_cs_count=1,
            wv_refugee_amount=2000,
        )
        self.client.force_login(wv_user)

        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"), {"department": wv_department.code})

        self.assertEqual(response.status_code, 200)
        payload = response.context["metrics_v2_payload"]
        self.assertEqual(payload["overall_summary"]["totals"]["decision_count"], 5)
        self.assertEqual(payload["overall_summary"]["totals"]["cs_count"], 3)
        self.assertEqual(payload["overall_summary"]["totals"]["refugee_count"], 2)
        self.assertEqual(payload["personal_summary"]["totals"]["decision_count"], 3)
        self.assertContains(response, "件数 5 / CM 9（CS 3件 / 難民 2件）")
        self.assertContains(response, "CS 3件 / 難民 2件")
        self.assertIn("cs_count", payload["ranking"]["metric_map"])
        self.assertIn("refugee_count", payload["ranking"]["metric_map"])
        self.assertEqual(payload["ranking"]["metric_map"]["decision_count"]["values"], [3, 2])
        self.assertContains(response, "CS限定の年代別決済比率")
        self.assertContains(response, "CS限定の男女比")
        self.assertContains(response, "CS限定の国籍比")

    def test_metrics_v2_demo_ranking_includes_inactive_member_with_scope_records(self):
        inactive_user, inactive_member = self.create_member_user(
            username="inactive_metrics_member",
            password="pass123",
            name="Inactive Metrics",
            department=self.department,
        )
        inactive_member.is_active = False
        inactive_member.save(update_fields=["is_active"])
        today = timezone.localdate()
        inactive_entry = MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=today,
            result_count=2,
            support_amount=2500,
            approach_count=5,
            communication_count=3,
        )
        MemberMetricTransaction.objects.create(
            entry=inactive_entry,
            support_amount=2500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="inactive metrics",
        )

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dairymetrics_metrics_v2_demo"),
            {"department": self.department.code, "scope": "custom", "start_date": today.strftime("%Y-%m-%d"), "end_date": today.strftime("%Y-%m-%d")},
        )

        self.assertEqual(response.status_code, 200)
        ranking_payload = response.context["metrics_v2_payload"]["ranking"]["metric_map"]["decision_count"]
        self.assertIn("Inactive Metrics", ranking_payload["labels"])

    def test_metrics_v2_demo_month_conversion_ranking_uses_base_entries_not_adjustments(self):
        target_month = date(2026, 3, 1)
        ranking_member = self.create_member(name="Conversion Base", department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=ranking_member,
            department=self.department,
            entry_date=date(2026, 3, 8),
            approach_count=20,
            communication_count=10,
            result_count=1,
            support_amount=3000,
            activity_closed=True,
        )
        MetricAdjustment.objects.create(
            member=ranking_member,
            department=self.department,
            target_date=date(2026, 3, 9),
            source_type=MetricAdjustment.SOURCE_INCREASE,
            result_count=9,
            support_amount=9000,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dairymetrics_metrics_v2_demo"),
            {
                "department": self.department.code,
                "scope": "month",
                "month": target_month.strftime("%Y-%m"),
            },
        )

        self.assertEqual(response.status_code, 200)
        ranking_payload = response.context["metrics_v2_payload"]["ranking"]["metric_map"]["conversion_rate"]
        rates_by_member = dict(zip(ranking_payload["labels"], ranking_payload["values"]))
        self.assertEqual(rates_by_member["Conversion Base"], 10.0)
