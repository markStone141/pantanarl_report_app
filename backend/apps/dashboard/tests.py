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

    def test_edit_member_keeps_password_when_blank(self):
        member = Member.objects.create(name="旧名", login_id="old_keep", password="keep_pw")

        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "更新名",
                "login_id": "old_keep",
                "password": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.password, "keep_pw")

    def test_register_member_requires_password(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "パスワードなし",
                "login_id": "no_pw_user",
                "password": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新規登録時はパスワードが必須です")
        self.assertFalse(Member.objects.filter(login_id="no_pw_user").exists())

    def test_delete_member_removes_record(self):
        member = Member.objects.create(name="削除対象", login_id="del_id", password="pw")

        response = self.client.post(reverse("member_delete", args=[member.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Member.objects.filter(id=member.id).exists())

    def test_register_member_with_departments_creates_links(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "所属あり",
                "login_id": "dept_user",
                "password": "pw",
                "departments": [self.depts["UN"].id, self.depts["STYLE1"].id],
            },
        )

        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(login_id="dept_user")
        self.assertEqual(
            set(member.department_links.values_list("department_id", flat=True)),
            {self.depts["UN"].id, self.depts["STYLE1"].id},
        )

    def test_edit_member_updates_departments(self):
        member = Member.objects.create(name="編成変更", login_id="move_user", password="pw")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])

        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "編成変更",
                "login_id": "move_user",
                "password": "pw",
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
        member = Member.objects.create(name="表示確認", login_id="show_user", password="pw")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])

        response = self.client.get(reverse("member_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN")


class DepartmentSettingsViewTests(TestCase):
    def setUp(self):
        self.un = Department.objects.create(name="UN", code="UN")
        self.member_a = Member.objects.create(name="責任者A", login_id="a", password="pw")
        self.member_b = Member.objects.create(name="責任者B", login_id="b", password="pw")
        MemberDepartment.objects.create(member=self.member_a, department=self.un)

    def test_update_department_sets_default_reporter(self):
        response = self.client.post(
            reverse("department_settings"),
            {
                "edit_department_id": str(self.un.id),
                "name": "UN",
                "code": "UN",
                "default_reporter": str(self.member_a.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.un.refresh_from_db()
        self.assertEqual(self.un.default_reporter_id, self.member_a.id)

    def test_update_department_rejects_non_member_as_default_reporter(self):
        response = self.client.post(
            reverse("department_settings"),
            {
                "edit_department_id": str(self.un.id),
                "name": "UN",
                "code": "UN",
                "default_reporter": str(self.member_b.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "候補にありません")
        self.un.refresh_from_db()
        self.assertIsNone(self.un.default_reporter_id)
