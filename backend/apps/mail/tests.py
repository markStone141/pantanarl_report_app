from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member

from .models import MailIntegrationSetting, MailRecipientGroup


User = get_user_model()


class MailManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mail-admin", password="pass1234", is_staff=True)
        self.client.force_login(self.user)
        self.department = Department.objects.create(code="UN", name="UN")
        self.member_one = Member.objects.create(name="Alice", email="alice@example.com")
        self.member_two = Member.objects.create(name="Bob", email="bob@example.com")

    def test_mail_settings_page_renders(self):
        response = self.client.get(reverse("mail_integration_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "メール連携設定")

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
            reverse("mail_integration_settings"),
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
                "department": self.department.id,
                "members": [self.member_one.id, self.member_two.id],
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        group = MailRecipientGroup.objects.get(name="当日共有A")
        self.assertEqual(group.members.count(), 2)

    def test_mail_settings_test_preview_shows_group_members(self):
        group = MailRecipientGroup.objects.create(name="共有B", department=self.department, is_active=True)
        group.members.set([self.member_one, self.member_two])
        response = self.client.post(
            reverse("mail_integration_settings"),
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
