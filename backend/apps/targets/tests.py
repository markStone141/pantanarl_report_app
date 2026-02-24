from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department

from .models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric


class TargetsFlowTests(TestCase):
    def setUp(self):
        Department.objects.create(name="UN", code="UN")
        Department.objects.create(name="WV", code="WV")
        Department.objects.create(name="Style1", code="STYLE1")
        Department.objects.create(name="Style2", code="STYLE2")

    def test_month_targets_save_with_auto_status(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)

        self.client.get(reverse("target_month_settings"))
        un_amount_metric = TargetMetric.objects.get(department__code="UN", code="amount")
        wv_cs_metric = TargetMetric.objects.get(department__code="WV", code="cs_count")

        response = self.client.post(
            reverse("target_month_settings"),
            {
                "action": "save_month_targets",
                "month": current_month.strftime("%Y-%m"),
                f"metric_{un_amount_metric.id}": "280000",
                f"metric_{wv_cs_metric.id}": "150",
            },
        )
        self.assertEqual(response.status_code, 302)

        un_value = MonthTargetMetricValue.objects.get(
            department__code="UN",
            target_month=current_month,
            metric=un_amount_metric,
        )
        self.assertEqual(un_value.value, 280000)
        self.assertEqual(un_value.status, "active")

        dashboard_response = self.client.get(reverse("target_index"))
        self.assertContains(dashboard_response, "active")

    def test_period_save_with_prefixed_name_and_auto_status(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        start_date = today - timedelta(days=1)
        end_date = today + timedelta(days=1)

        self.client.get(reverse("target_period_settings"))
        response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        period = Period.objects.get(name=f"{current_month.year}年度{current_month.month}月 第1次路程")
        self.assertEqual(period.status, "active")

    def test_period_targets_are_saved(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        start_date = today - timedelta(days=1)
        end_date = today + timedelta(days=1)

        self.client.get(reverse("target_period_settings"))
        self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        period = Period.objects.get(name=f"{current_month.year}年度{current_month.month}月 第1次路程")
        un_count_metric = TargetMetric.objects.get(department__code="UN", code="count")
        wv_refugee_metric = TargetMetric.objects.get(department__code="WV", code="refugee_count")

        response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period_targets",
                "selected_period_id": str(period.id),
                f"metric_{un_count_metric.id}": "45",
                f"metric_{wv_refugee_metric.id}": "39",
            },
        )
        self.assertEqual(response.status_code, 200)

        un_value = PeriodTargetMetricValue.objects.get(
            period=period,
            department__code="UN",
            metric=un_count_metric,
        )
        self.assertEqual(un_value.value, 45)

    def test_period_duplicate_save_updates_existing_instead_of_error(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)

        self.client.get(reverse("target_period_settings"))
        first = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": (today + timedelta(days=1)).isoformat(),
                "end_date": (today + timedelta(days=2)).isoformat(),
            },
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": (today - timedelta(days=2)).isoformat(),
                "end_date": (today - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(second.status_code, 200)
        name = f"{current_month.year}年度{current_month.month}月 第1次路程"
        self.assertEqual(Period.objects.filter(month=current_month, name=name).count(), 1)
        period = Period.objects.get(month=current_month, name=name)
        self.assertEqual(period.status, "finished")
