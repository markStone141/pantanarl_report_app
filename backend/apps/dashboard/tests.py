from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member, MemberDepartment
from apps.targets.models import TargetMetric


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
                "name": "Test Member",
            },
        )
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(name="Test Member")
        self.assertTrue(member.login_id.startswith("test-member"))

    def test_edit_member_updates_name(self):
        member = Member.objects.create(name="Old Name", login_id="old", password="")
        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "New Name",
            },
        )
        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.name, "New Name")
        self.assertEqual(member.login_id, "old")

    def test_delete_member_removes_record(self):
        member = Member.objects.create(name="Delete User", login_id="del_id", password="")
        response = self.client.post(reverse("member_delete", args=[member.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Member.objects.filter(id=member.id).exists())

    def test_register_member_with_departments_creates_links(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "Dept User",
                "departments": [self.depts["UN"].id, self.depts["STYLE1"].id],
            },
        )
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(name="Dept User")
        self.assertEqual(
            set(member.department_links.values_list("department_id", flat=True)),
            {self.depts["UN"].id, self.depts["STYLE1"].id},
        )

    def test_edit_member_updates_departments(self):
        member = Member.objects.create(name="Move User", login_id="move_user", password="")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])
        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "Move User",
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
        member = Member.objects.create(name="Show User", login_id="show_user", password="")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])
        response = self.client.get(reverse("member_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN")


class DepartmentSettingsViewTests(TestCase):
    def setUp(self):
        self.depts = seed_departments()
        self.member_un = Member.objects.create(name="UN Leader", login_id="un_leader", password="")
        self.member_wv = Member.objects.create(name="WV Leader", login_id="wv_leader", password="")
        MemberDepartment.objects.create(member=self.member_un, department=self.depts["UN"])
        MemberDepartment.objects.create(member=self.member_wv, department=self.depts["WV"])
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_create_department(self):
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_department",
                "name": "New Team",
                "code": "NEWTEAM",
                "default_reporter": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Department.objects.filter(code="NEWTEAM", name="New Team").exists())

    def test_update_department_with_default_reporter(self):
        department = self.depts["UN"]
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_department",
                "edit_department_id": str(department.id),
                "name": "UN Updated",
                "code": "UN",
                "default_reporter": str(self.member_un.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        department.refresh_from_db()
        self.assertEqual(department.name, "UN Updated")
        self.assertEqual(department.default_reporter_id, self.member_un.id)

    def test_update_department_rejects_reporter_outside_department(self):
        department = self.depts["UN"]
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_department",
                "edit_department_id": str(department.id),
                "name": "UN Updated",
                "code": "UN",
                "default_reporter": str(self.member_wv.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        department.refresh_from_db()
        self.assertNotEqual(department.default_reporter_id, self.member_wv.id)

    def test_delete_department(self):
        department = Department.objects.create(name="To Delete", code="DEL_TEAM")
        response = self.client.post(reverse("department_delete", args=[department.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Department.objects.filter(id=department.id).exists())

    def test_create_metric_for_department(self):
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_metric",
                "metric_department_id": str(self.depts["UN"].id),
                "label": "Contracts",
                "code": "contracts",
                "unit": "item",
                "display_order": "1",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            TargetMetric.objects.filter(
                department=self.depts["UN"],
                code="contracts",
                label="Contracts",
            ).exists()
        )

    def test_update_metric(self):
        metric = TargetMetric.objects.create(
            department=self.depts["UN"],
            code="amount_extra",
            label="Amount Extra",
            unit="yen",
            display_order=3,
            is_active=True,
        )
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_metric",
                "metric_department_id": str(self.depts["UN"].id),
                "edit_metric_id": str(metric.id),
                "label": "Amount Updated",
                "code": "amount_extra",
                "unit": "yen",
                "display_order": "5",
            },
        )
        self.assertEqual(response.status_code, 200)
        metric.refresh_from_db()
        self.assertEqual(metric.label, "Amount Updated")
        self.assertEqual(metric.display_order, 5)

    def test_toggle_metric_active_state(self):
        metric = TargetMetric.objects.create(
            department=self.depts["UN"],
            code="toggle_target",
            label="Toggle Target",
            unit="item",
            display_order=4,
            is_active=True,
        )
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "toggle_metric",
                "metric_id": str(metric.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        metric.refresh_from_db()
        self.assertFalse(metric.is_active)
