from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, MemberDepartment
from apps.common.test_helpers import AppTestMixin
from .models import DepartmentDailyMetricSummary, MemberDailyMetricEntry


class MainDepartmentPreparationTests(AppTestMixin, TestCase):
    def setUp(self):
        self.main = Department.objects.create(code="UNW", name="UN関西")
        self.other = Department.objects.create(code="UN", name="UN")
        self.user, self.member = self.create_member_user(
            username="main-department-member", name="関西メンバー", department=self.main,
        )
        MemberDepartment.objects.create(member=self.member, department=self.other)
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def assert_selected(self, department, query=None):
        response = self.client.get(reverse("dairymetrics_entry_v2_transaction_demo"), query or {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_department_code"], department.code)
        field = response.context["personal_setup_form"]["department"]
        self.assertEqual(str(field.value()), str(department.pk))
        self.assertInHTML(
            f'<option value="{department.pk}" selected>{department}</option>', str(field),
        )
        return response

    def test_preparation_defaults_to_main_instead_of_first_department(self):
        self.assert_selected(self.main)

    def test_main_department_takes_priority_over_existing_daily_entry(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member, department=self.other, entry_date=self.today, daily_target_amount=9000,
        )
        self.assert_selected(self.main)
        entry.refresh_from_db()
        self.assertEqual(entry.daily_target_amount, 9000)
        self.assertFalse(MemberDailyMetricEntry.objects.filter(member=self.member, department=self.main).exists())

    def test_main_department_takes_priority_over_department_summary(self):
        DepartmentDailyMetricSummary.objects.create(
            department=self.other, entry_date=self.today, daily_target_amount=9000,
        )
        self.assert_selected(self.main)

    def test_explicit_department_selection_overrides_main(self):
        self.assert_selected(self.other, {"department": self.other.code})
        response = self.client.get(reverse("dairymetrics_entry_v2_personal_setup_fields"), {
            "department": self.other.pk, "entry_date": self.today.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'<option value="{self.other.pk}" selected>', response.json()["setup_html"])

    def test_main_without_membership_does_not_become_selected(self):
        outsider = Department.objects.create(code="OUTSIDE", name="所属外")
        self.member.default_department = outsider
        self.member.save(update_fields=["default_department"])
        response = self.assert_selected(self.other)
        self.assertNotIn(outsider, response.context["personal_setup_form"].fields["department"].queryset)

    def test_inactive_main_does_not_become_selected(self):
        self.main.is_active = False
        self.main.save(update_fields=["is_active"])
        self.assert_selected(self.other)

    def test_missing_main_falls_back_to_existing_daily_entry(self):
        self.member.default_department = None
        self.member.save(update_fields=["default_department"])
        MemberDailyMetricEntry.objects.create(member=self.member, department=self.main, entry_date=self.today)
        self.assert_selected(self.main)
