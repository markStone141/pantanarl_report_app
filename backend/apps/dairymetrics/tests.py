from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member, MemberDepartment

from .models import MemberDailyMetricEntry, MetricAdjustment


class DairyMetricsLoginTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="member1", password="pass123")
        self.member = Member.objects.create(name="Member One", user=self.user)
        self.department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=self.department)

    def test_member_can_login(self):
        response = self.client.post(
            reverse("dairymetrics_login"),
            {"login_id": "member1", "password": "pass123"},
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard"))

    def test_non_member_user_is_rejected(self):
        get_user_model().objects.create_user(username="outsider", password="pass123")
        response = self.client.post(
            reverse("dairymetrics_login"),
            {"login_id": "outsider", "password": "pass123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DairyMetrics を利用できるメンバーではありません。")


class DairyMetricsDashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="member2", password="pass123")
        self.member = Member.objects.create(name="Member Two", user=self.user)
        self.department = Department.objects.create(code="WV", name="WV")
        MemberDepartment.objects.create(member=self.member, department=self.department)

    def test_dashboard_aggregates_entries_and_adjustments(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=10,
            communication_count=6,
            result_count=2,
            support_amount=4000,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 3, 9),
            result_count=1,
            support_amount=2000,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dairymetrics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "6,000")
        self.assertContains(response, "3")
        self.assertContains(response, "10")

    def test_entry_form_updates_existing_record(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 3, 9),
            approach_count=5,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("dairymetrics_entry"),
            {
                "department": self.department.id,
                "entry_date": "2026-03-09",
                "approach_count": 9,
                "communication_count": 4,
                "result_count": 2,
                "support_amount": 3000,
                "cs_count": 1,
                "refugee_count": 1,
                "location_name": "Tokyo",
                "memo": "updated",
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_dashboard") + "?saved=1")
        entry.refresh_from_db()
        self.assertEqual(entry.approach_count, 9)
        self.assertEqual(MemberDailyMetricEntry.objects.count(), 1)

    def test_dashboard_ajax_switches_department_and_prefills_form(self):
        second_department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=second_department)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=second_department,
            entry_date=date(2026, 3, 9),
            approach_count=7,
            communication_count=3,
            result_count=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("dairymetrics_dashboard"),
            {"department": "UN"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["department_code"], "UN")
        self.assertIn("UN", payload["card_html"])
        self.assertIn('value="7"', payload["form_html"])


class DairyMetricsAdminTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="admin_user", password="pass123", is_staff=True)
        self.member = Member.objects.create(name="Member Three")
        self.department = Department.objects.create(code="UN", name="UN")
        MemberDepartment.objects.create(member=self.member, department=self.department)

    def test_admin_overview_requires_staff(self):
        response = self.client.get(reverse("dairymetrics_admin_overview"))
        self.assertRedirects(response, reverse("dairymetrics_login"))

    def test_admin_can_create_adjustment(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("dairymetrics_adjustment_create"),
            {
                "member": self.member.id,
                "department": self.department.id,
                "target_date": "2026-03-09",
                "source_type": "postal",
                "approach_count": 0,
                "communication_count": 0,
                "result_count": 1,
                "support_amount": 5000,
                "cs_count": 0,
                "refugee_count": 0,
                "note": "late postal",
            },
        )
        self.assertRedirects(response, reverse("dairymetrics_admin_overview") + "?month=2026-03")
        adjustment = MetricAdjustment.objects.get()
        self.assertEqual(adjustment.created_by, self.admin)
        self.assertEqual(adjustment.source_type, "postal")
