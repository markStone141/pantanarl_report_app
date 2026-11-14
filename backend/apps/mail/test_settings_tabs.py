from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department
from apps.mail.models import MailRecipientGroup


class MailSettingsTabTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_all_existing_sections_are_tabs(self):
        response = self.client.get(reverse("mail_group_settings"))
        self.assertEqual(response.status_code, 200)
        for tab_id in ("groups", "edit", "routing", "gmail", "test", "test-history"):
            with self.subTest(tab_id=tab_id):
                self.assertContains(response, 'id="mail-tab-' + tab_id + '"')
                self.assertContains(response, 'id="mail-panel-' + tab_id + '"')
        self.assertContains(response, reverse("mail_history"))
        self.assertNotContains(response, "<details")

    def test_existing_edit_link_opens_edit_tab(self):
        group = MailRecipientGroup.objects.create(name="テストグループ")
        response = self.client.get(reverse("mail_group_settings") + f"?edit={group.pk}")
        self.assertContains(response, "メールグループ編集")
        self.assertContains(response, 'const suggestedTab = "edit";')

    def test_routing_save_still_works(self):
        department = Department.objects.create(name="UN", code="UN")
        group = MailRecipientGroup.objects.create(name="報告先")
        response = self.client.post(reverse("mail_group_settings"), {
            "action": "save_routing", "un_group": str(group.pk),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(department.mail_routing.recipient_group, group)
        self.assertContains(response, "決済報告の既定メールグループを更新しました。")

    def test_group_creation_still_works(self):
        response = self.client.post(reverse("mail_group_settings"), {
            "name": "新規グループ", "is_active": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MailRecipientGroup.objects.filter(name="新規グループ").exists())
