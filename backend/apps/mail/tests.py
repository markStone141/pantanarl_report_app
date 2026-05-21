from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.accounts.models import Department, Member, MemberDepartment

from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction

from .models import MailDepartmentRouting, MailIntegrationSetting, MailRecipientGroup, MailSendHistory
from .services import MailSendError, record_transaction_mail_failure, send_transaction_mail_mock


User = get_user_model()


class MailManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mail-admin", password="pass1234", is_staff=True)
        self.client.force_login(self.user)
        self.department = Department.objects.create(code="UN", name="UN")
        self.other_department = Department.objects.create(code="WV", name="WV")
        self.member_one = Member.objects.create(name="Alice", email="alice@example.com")
        self.member_two = Member.objects.create(name="Bob", email="bob@example.com")
        self.member_three = Member.objects.create(name="Carol", email="carol@example.com")
        MemberDepartment.objects.create(member=self.member_one, department=self.department)
        MemberDepartment.objects.create(member=self.member_two, department=self.other_department)
        MemberDepartment.objects.create(member=self.member_three, department=self.department)
        MemberDepartment.objects.create(member=self.member_three, department=self.other_department)

    def test_mail_settings_page_renders(self):
        response = self.client.get(reverse("mail_integration_settings"))
        self.assertRedirects(response, reverse("mail_group_settings"))

    def test_mail_settings_preserve_existing_secrets_when_blank(self):
        setting = MailIntegrationSetting.objects.create(
            sender_email="before@example.com",
            sender_name="Before",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            is_active=True,
        )
        response = self.client.post(
            reverse("mail_group_settings"),
            {
                "action": "save_settings",
                "sender_email": "after@example.com",
                "sender_name": "After",
                "token_uri": "https://oauth2.googleapis.com/token",
                "is_active": "on",
                "client_id": "",
                "client_secret": "",
                "refresh_token": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        setting.refresh_from_db()
        self.assertEqual(setting.sender_email, "after@example.com")
        self.assertEqual(setting.client_id, "client-id")
        self.assertEqual(setting.client_secret, "client-secret")
        self.assertEqual(setting.refresh_token, "refresh-token")

    def test_mail_group_create_saves_member_links(self):
        response = self.client.post(
            reverse("mail_group_settings"),
            {
                "name": "当日共有A",
                "departments": [self.department.id, self.other_department.id],
                "members": [self.member_one.id, self.member_two.id],
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        group = MailRecipientGroup.objects.get(name="当日共有A")
        self.assertEqual(group.members.count(), 2)
        self.assertEqual(
            list(group.related_departments.order_by("code").values_list("code", flat=True)),
            ["UN", "WV"],
        )
        self.assertEqual(group.department, self.department)

    def test_mail_group_member_options_filters_by_selected_departments(self):
        response = self.client.get(
            reverse("mail_group_member_options"),
            {"departments": [self.department.id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [item["name"] for item in payload["members"]]
        self.assertEqual(names, ["Alice", "Carol"])

    def test_mail_group_settings_saves_default_routing_for_un_and_wv(self):
        un_group = MailRecipientGroup.objects.create(name="UN共有", is_active=True)
        wv_group = MailRecipientGroup.objects.create(name="WV共有", is_active=True)

        response = self.client.post(
            reverse("mail_group_settings"),
            {
                "action": "save_routing",
                "un_group": un_group.id,
                "wv_group": wv_group.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            MailDepartmentRouting.objects.get(department=self.department).recipient_group,
            un_group,
        )
        self.assertEqual(
            MailDepartmentRouting.objects.get(department=self.other_department).recipient_group,
            wv_group,
        )

    def test_mail_group_delete_removes_group_and_related_routing(self):
        group = MailRecipientGroup.objects.create(name="削除対象", department=self.department, is_active=True)
        MailDepartmentRouting.objects.create(department=self.department, recipient_group=group)

        response = self.client.post(reverse("mail_group_delete", args=[group.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(MailRecipientGroup.objects.filter(id=group.id).exists())
        self.assertFalse(MailDepartmentRouting.objects.filter(department=self.department).exists())

    def test_mail_settings_test_preview_shows_group_members(self):
        group = MailRecipientGroup.objects.create(name="共有B", department=self.department, is_active=True)
        group.members.set([self.member_one, self.member_two])
        response = self.client.post(
            reverse("mail_group_settings"),
            {
                "action": "test_preview",
                "target_type": "group",
                "group": group.id,
                "member": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alice@example.com")
        self.assertContains(response, "bob@example.com")

    def test_mail_group_settings_renders_integrated_mail_sections(self):
        response = self.client.get(reverse("mail_group_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "メールグループ一覧")
        self.assertContains(response, "Gmail連携設定")
        self.assertContains(response, "決済報告用メールグループ設定")

    @patch("apps.mail.services._send_via_gmail", return_value="gmail-message-1")
    def test_mail_settings_test_send_creates_sent_history(self, mocked_send):
        MailIntegrationSetting.objects.create(
            sender_email="sender@example.com",
            sender_name="Sender",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            is_active=True,
        )
        response = self.client.post(
            reverse("mail_group_settings"),
            {
                "action": "test_send",
                "target_type": "member",
                "member": self.member_one.id,
                "group": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        history = MailSendHistory.objects.get(is_test=True)
        self.assertEqual(history.status, MailSendHistory.STATUS_SENT)
        self.assertEqual(history.provider_message_id, "gmail-message-1")
        self.assertIn("alice@example.com", history.sent_to_snapshot)
        mocked_send.assert_called_once()

    @patch(
        "apps.mail.services._send_via_gmail",
        side_effect=MailSendError("Gmail送信に失敗しました。", code="invalid_grant", detail="Token has been expired or revoked."),
    )
    def test_mail_settings_test_send_creates_failed_history(self, mocked_send):
        MailIntegrationSetting.objects.create(
            sender_email="sender@example.com",
            sender_name="Sender",
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            is_active=True,
        )
        group = MailRecipientGroup.objects.create(name="共有B", department=self.department, is_active=True)
        group.members.set([self.member_one, self.member_three])
        response = self.client.post(
            reverse("mail_group_settings"),
            {
                "action": "test_send",
                "target_type": "group",
                "member": "",
                "group": group.id,
            },
        )
        self.assertEqual(response.status_code, 200)
        history = MailSendHistory.objects.get(is_test=True)
        self.assertEqual(history.status, MailSendHistory.STATUS_FAILED)
        self.assertEqual(history.error_code, "invalid_grant")
        self.assertIn("expired or revoked", history.error_message)
        self.assertEqual(history.recipient_group, group)
        mocked_send.assert_called_once()

    def test_send_transaction_mail_mock_creates_sent_history(self):
        group = MailRecipientGroup.objects.create(name="共有B", department=self.department, is_active=True)
        group.members.set([self.member_one, self.member_two])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member_one,
            department=self.department,
            entry_date=timezone.localdate(),
            daily_target_count=1,
            daily_target_amount=3000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=1000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            is_student=True,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="テスト",
        )

        history = send_transaction_mail_mock(
            sender_member=self.member_one,
            transaction=transaction,
            recipient_group=group,
            subject="件名",
            body="本文",
        )

        self.assertEqual(history.status, MailSendHistory.STATUS_SENT)
        self.assertEqual(history.transaction, transaction)
        self.assertEqual(history.recipient_group, group)
        self.assertIn("alice@example.com", history.sent_to_snapshot)
        self.assertIn("bob@example.com", history.sent_to_snapshot)

    def test_record_transaction_mail_failure_saves_failed_history(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member_one,
            department=self.department,
            entry_date=timezone.localdate(),
            daily_target_count=1,
            daily_target_amount=3000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=1000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            is_student=False,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="テスト",
        )

        history = record_transaction_mail_failure(
            sender_member=self.member_one,
            transaction=transaction,
            recipient_group=None,
            subject="件名",
            body="本文",
            error_code="RuntimeError",
            error_message="gmail timeout",
        )

        self.assertEqual(history.status, MailSendHistory.STATUS_FAILED)
        self.assertEqual(history.error_code, "RuntimeError")
        self.assertEqual(history.error_message, "gmail timeout")
        self.assertIsNone(history.sent_at)
        self.assertIsNotNone(history.last_attempt_at)
