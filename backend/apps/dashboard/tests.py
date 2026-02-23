from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Member


class MemberSettingsViewTests(TestCase):
    def test_register_member_creates_record(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "テスト太郎",
                "login_id": "un_test",
                "password": "secret",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Member.objects.filter(login_id="un_test").exists())
        self.assertContains(response, "登録しました")

    def test_duplicate_login_id_shows_error(self):
        Member.objects.create(name="A", login_id="dup_id", password="x")

        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "B",
                "login_id": "dup_id",
                "password": "y",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "既に使われています")
        self.assertEqual(Member.objects.filter(login_id="dup_id").count(), 1)

    def test_edit_member_updates_record(self):
        member = Member.objects.create(name="旧名", login_id="old_id", password="old_pw")

        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "新名",
                "login_id": "new_id",
                "password": "new_pw",
            },
        )

        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.name, "新名")
        self.assertEqual(member.login_id, "new_id")
        self.assertEqual(member.password, "new_pw")
        self.assertContains(response, "更新しました")

    def test_delete_member_removes_record(self):
        member = Member.objects.create(name="削除対象", login_id="del_id", password="pw")

        response = self.client.post(reverse("member_delete", args=[member.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Member.objects.filter(id=member.id).exists())
