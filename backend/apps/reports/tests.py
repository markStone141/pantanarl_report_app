from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member, MemberDepartment


class ReportMemberFilteringTests(TestCase):
    def test_report_un_shows_only_un_members(self):
        un = Department.objects.create(name="UN", code="UN")
        wv = Department.objects.create(name="WV", code="WV")
        un_member = Member.objects.create(name="UN担当", login_id="un_a", password="x")
        wv_member = Member.objects.create(name="WV担当", login_id="wv_a", password="y")
        MemberDepartment.objects.create(member=un_member, department=un)
        MemberDepartment.objects.create(member=wv_member, department=wv)

        response = self.client.get(reverse("report_un"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN担当")
        self.assertNotContains(response, "WV担当")
