from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department

from .models import DepartmentMonthTarget, DepartmentPeriodTarget, Period


class TargetsFlowTests(TestCase):
    def setUp(self):
        Department.objects.create(name="UN", code="UN")
        Department.objects.create(name="WV", code="WV")
        Department.objects.create(name="Style1", code="STYLE1")
        Department.objects.create(name="Style2", code="STYLE2")

    def test_month_targets_are_saved_and_reflected_on_dashboard(self):
        response = self.client.post(
            reverse("target_month_settings"),
            {
                "action": "save_month_targets",
                "month": "2026-02",
                "count_UN": "180",
                "amount_UN": "280000",
                "count_WV": "150",
                "amount_WV": "180000",
                "count_STYLE1": "120",
                "amount_STYLE1": "400000",
                "count_STYLE2": "90",
                "amount_STYLE2": "450000",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DepartmentMonthTarget.objects.count(), 4)
        target = DepartmentMonthTarget.objects.get(department__code="UN")
        self.assertEqual(target.target_count, 180)
        self.assertEqual(target.target_amount, 280000)

        dashboard_response = self.client.get(reverse("target_index"))
        self.assertContains(dashboard_response, "2026年2月")
        self.assertContains(dashboard_response, "280000")

    def test_period_and_period_targets_are_saved(self):
        response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": "2026-02",
                "period_sequence": "1",
                "start_date": "2026-02-10",
                "end_date": "2026-02-15",
            },
        )
        self.assertEqual(response.status_code, 200)
        period = Period.objects.get(name="第1次路程")
        self.assertEqual(period.month.isoformat(), "2026-02-01")

        response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period_targets",
                "selected_period_id": str(period.id),
                "count_UN": "45",
                "amount_UN": "88000",
                "count_WV": "39",
                "amount_WV": "60000",
                "count_STYLE1": "28",
                "amount_STYLE1": "136000",
                "count_STYLE2": "30",
                "amount_STYLE2": "150000",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DepartmentPeriodTarget.objects.count(), 4)
        target = DepartmentPeriodTarget.objects.get(period=period, department__code="UN")
        self.assertEqual(target.target_count, 45)
        self.assertEqual(target.target_amount, 88000)

        dashboard_response = self.client.get(reverse("target_index"))
        self.assertContains(dashboard_response, "第1次路程")
        self.assertContains(dashboard_response, "88000")
