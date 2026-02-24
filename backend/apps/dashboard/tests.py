from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member, MemberDepartment


def seed_departments():
    return {
        "UN": Department.objects.create(name="UN", code="UN"),
        "WV": Department.objects.create(name="WV", code="WV"),
        "STYLE1": Department.objects.create(name="Style1", code="STYLE1"),
        "STYLE2": Department.objects.create(name="Style2", code="STYLE2"),
    }


class MemberSettingsViewTests(TestCase):
    def setUp(self):
        self.depts = seed_departments()
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_register_member_creates_record(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "テスト太郎",
            },
        )
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(name="テスト太郎")
        self.assertTrue(member.login_id.startswith("member"))
        self.assertContains(response, "登録しました")

    def test_edit_member_updates_name(self):
        member = Member.objects.create(name="旧名", login_id="old", password="")
        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "新名",
            },
        )
        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.name, "新名")
        self.assertEqual(member.login_id, "old")
        self.assertContains(response, "更新しました")

    def test_delete_member_removes_record(self):
        member = Member.objects.create(name="削除対象", login_id="del_id", password="")
        response = self.client.post(reverse("member_delete", args=[member.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Member.objects.filter(id=member.id).exists())

    def test_register_member_with_departments_creates_links(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "部署あり",
                "departments": [self.depts["UN"].id, self.depts["STYLE1"].id],
            },
        )
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(name="部署あり")
        self.assertEqual(
            set(member.department_links.values_list("department_id", flat=True)),
            {self.depts["UN"].id, self.depts["STYLE1"].id},
        )

    def test_edit_member_updates_departments(self):
        member = Member.objects.create(name="異動対象", login_id="move_user", password="")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])
        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "異動対象",
                "departments": [self.depts["WV"].id],
            },
        )
        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(
            set(member.department_links.values_list("department_id", flat=True)),
            {self.depts["WV"].id},
        )

    def test_member_list_shows_department_name(self):
        member = Member.objects.create(name="表示確認", login_id="show_user", password="")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])
        response = self.client.get(reverse("member_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN")
