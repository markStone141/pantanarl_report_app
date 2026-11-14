from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member
from apps.mail.models import MailRecipientGroup, MailRecipientGroupMember, MailSendHistory


class MemberRegistrationMailTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()
        self.department = Department.objects.create(name="UN", code="UN")
        self.group = MailRecipientGroup.objects.create(name="UN報告")

    def test_registration_shows_mail_options(self):
        response = self.client.get(reverse("member_create"))
        self.assertContains(response, "メールグループ・確認メール")
        self.assertContains(response, "実績管理アプリログイン時のIDとパスワードです。")
        self.assertContains(response, self.group.name)
        self.assertContains(response, "send_confirmation_mail")

    def test_confirmation_mail_uses_same_selection_card_as_mail_groups(self):
        response = self.client.get(reverse("member_create"))
        self.assertContains(response, 'class="selection-card__input" type="checkbox" name="send_confirmation_mail"')
        self.assertContains(response, 'for="id_send_confirmation_mail"')
        self.assertContains(response, 'class="selection-card__check"')
        self.assertContains(response, 'class="selection-card__title"')

    @patch("apps.dashboard.views.send_test_mail")
    def test_registers_member_and_group_without_sending_by_default(self, send_mail):
        response = self.client.post(reverse("member_create"), {
            "name": "登録者", "email": "new@example.com",
            "departments": [str(self.department.pk)],
            "default_department": str(self.department.pk),
            "mail_groups": [str(self.group.pk)],
        })
        member = Member.objects.get(name="登録者")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MailRecipientGroupMember.objects.filter(member=member, group=self.group).exists())
        send_mail.assert_not_called()

    @patch("apps.dashboard.views.send_test_mail")
    def test_opt_in_sends_to_new_member(self, send_mail):
        send_mail.return_value = Mock(status=MailSendHistory.STATUS_SENT)
        response = self.client.post(reverse("member_create"), {
            "name": "確認者", "email": "confirm@example.com",
            "mail_groups": [str(self.group.pk)],
            "send_confirmation_mail": "on",
        })
        member = Member.objects.get(name="確認者")
        send_mail.assert_called_once_with(target_member=member)
        self.assertTrue(MailRecipientGroupMember.objects.filter(member=member, group=self.group).exists())
        self.assertContains(response, "確認メールを送信しました")

    @patch("apps.dashboard.views.send_test_mail")
    def test_failed_mail_keeps_registration(self, send_mail):
        send_mail.return_value = Mock(status=MailSendHistory.STATUS_FAILED)
        response = self.client.post(reverse("member_create"), {
            "name": "失敗者", "email": "fail@example.com",
            "send_confirmation_mail": "on",
        })
        self.assertTrue(Member.objects.filter(name="失敗者").exists())
        self.assertContains(response, "確認メールの送信に失敗しました")

    @patch("apps.dashboard.views.send_test_mail")
    def test_no_email_rejects_opt_in(self, send_mail):
        response = self.client.post(reverse("member_create"), {
            "name": "宛先なし", "send_confirmation_mail": "on",
        })
        self.assertFalse(Member.objects.filter(name="宛先なし").exists())
        self.assertContains(response, "確認メールを送信する場合はメールアドレスを入力してください")
        send_mail.assert_not_called()

    def test_inactive_group_cannot_be_assigned(self):
        self.group.is_active = False
        self.group.save(update_fields=["is_active"])
        response = self.client.post(reverse("member_create"), {
            "name": "拒否", "mail_groups": [str(self.group.pk)],
        })
        self.assertFalse(Member.objects.filter(name="拒否").exists())
        self.assertEqual(response.status_code, 200)
