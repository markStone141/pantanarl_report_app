from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.common.test_helpers import AppTestMixin
from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction
from apps.dairymetrics.services.entry_v2 import build_transaction_mail_preview


class ActivityStartCommentTests(AppTestMixin, TestCase):
    def setUp(self):
        self.department = self.create_department("UN")
        self.user, self.member = self.create_member_user(
            username="comment_member",
            password="pass123",
            name="意気込みメンバー",
            department=self.department,
        )
        self.admin = self.create_user("comment_admin", password="pass123", is_staff=True)
        self.today = timezone.localdate()

    def _save_setup(self, comment):
        self.client.force_login(self.user)
        return self.client.post(
            reverse("dairymetrics_entry_v2_transaction_demo"),
            {
                "action": "save_personal_setup",
                "department": str(self.department.pk),
                "entry_date": self.today.isoformat(),
                "location_name": "駅前",
                "daily_target_count": "3",
                "daily_target_amount": "9000",
                "start_comment": comment,
            },
        )

    def test_optional_comment_is_saved_and_can_be_changed(self):
        response = self._save_setup("まずは声かけを頑張る！")
        self.assertEqual(response.status_code, 302)
        entry = MemberDailyMetricEntry.objects.get(
            member=self.member, department=self.department, entry_date=self.today
        )
        self.assertEqual(entry.start_comment, "まずは声かけを頑張る！")
        self.assertEqual(entry.memo, "")
        response = self.client.get(reverse("dairymetrics_entry_v2_transaction_demo"))
        self.assertContains(response, "まずは声かけを頑張る！")

        response = self._save_setup("")
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.start_comment, "")

    def test_quick_status_can_be_updated_repeatedly_without_changing_targets(self):
        self._save_setup("最初のひとこと")
        url = reverse("dairymetrics_entry_v2_transaction_demo")
        for comment in ("2件目を目指す", "あと少し！", ""):
            response = self.client.post(url, {
                "action": "save_start_comment",
                "department_code": self.department.code,
                "entry_date": self.today.isoformat(),
                "start_comment": comment,
            })
            self.assertEqual(response.status_code, 302)
            entry = MemberDailyMetricEntry.objects.get(
                member=self.member, department=self.department, entry_date=self.today
            )
            self.assertEqual(entry.start_comment, comment)
            self.assertEqual(entry.daily_target_amount, 9000)
            self.assertEqual(entry.daily_target_count, 3)

    def test_overlong_status_is_rejected(self):
        self._save_setup("")
        response = self.client.post(reverse("dairymetrics_entry_v2_transaction_demo"), {
            "action": "save_start_comment",
            "department_code": self.department.code,
            "entry_date": self.today.isoformat(),
            "start_comment": "あ" * 101,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "100文字以内")

    def test_comment_displays_only_on_active_dashboard_card(self):
        self._save_setup("今日は3件を目指す")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("performance_index"))
        self.assertContains(response, "今日の意気込み：")
        self.assertContains(response, "今日は3件を目指す")
        entry = MemberDailyMetricEntry.objects.get(
            member=self.member, department=self.department, entry_date=self.today
        )
        entry.activity_closed = True
        entry.save(update_fields=["activity_closed"])
        response = self.client.get(reverse("performance_index"))
        self.assertNotContains(response, "今日の意気込み：")

    def test_acquisition_mail_adds_comment_after_target_amount(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member, department=self.department, entry_date=self.today,
            daily_target_amount=9000, start_comment="今日も一歩ずつ！",
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
        )
        cards = [
            {"current_amount": 3000, "target_amount": 9000},
            {"signed_gap_amount": 1000},
            {"signed_gap_amount": 2000},
            {"signed_gap_amount": 3000},
        ]
        payload = build_transaction_mail_preview(
            member=self.member, department_code="UN",
            transaction_obj=transaction, progress_cards=cards,
        )
        self.assertTrue(payload["body"].endswith("3,000/9,000円\n今日の意気込み：今日も一歩ずつ！"))
        entry.start_comment = ""
        entry.save(update_fields=["start_comment"])
        payload = build_transaction_mail_preview(
            member=self.member, department_code="UN",
            transaction_obj=transaction, progress_cards=cards,
        )
        self.assertTrue(payload["body"].endswith("3,000/9,000円"))
        self.assertNotIn("今日の意気込み", payload["body"])

    def test_new_entries_default_to_blank_comment(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member, department=self.department, entry_date=self.today
        )
        self.assertEqual(entry.start_comment, "")
