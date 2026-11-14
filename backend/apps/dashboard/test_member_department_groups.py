from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member, MemberDepartment


class DepartmentGroupedMemberListTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()
        self.un = Department.objects.create(name="UN東京", code="UN")
        self.wv = Department.objects.create(name="WV東京", code="WV")
        self.shared = Member.objects.create(name="共通メンバー")
        MemberDepartment.objects.create(member=self.shared, department=self.un)
        MemberDepartment.objects.create(member=self.shared, department=self.wv)
        self.unassigned = Member.objects.create(name="未所属メンバー")

    def test_default_groups_are_collapsed_and_shared_member_is_in_both(self):
        response = self.client.get(reverse("member_settings"))
        self.assertEqual(response.status_code, 200)
        sections = response.context["member_sections"]
        self.assertEqual([section["department"].name if section["department"] else None for section in sections],
                         ["UN東京", "WV東京", None])
        self.assertEqual([member.name for member in sections[0]["members"]], ["共通メンバー"])
        self.assertEqual([member.name for member in sections[1]["members"]], ["共通メンバー"])
        self.assertFalse(response.context["expand_groups"])
        self.assertContains(response, 'class="member-department-group card"', count=3)
        self.assertContains(response, "未所属・非表示部署")

    def test_query_expands_matching_department(self):
        response = self.client.get(reverse("member_settings"), {"q": "共通"})
        self.assertTrue(response.context["expand_groups"])
        self.assertEqual(len(response.context["member_sections"]), 2)
        self.assertContains(response, 'class="member-department-group card" open', count=2)

    def test_ajax_refresh_returns_group_html(self):
        response = self.client.get(reverse("member_settings"), {"q": "未所属"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        html = response.json()["list_html"]
        self.assertIn("未所属・非表示部署", html)
        self.assertIn("未所属メンバー", html)
        self.assertNotIn("共通メンバー", html)
