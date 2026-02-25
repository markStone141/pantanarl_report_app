from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department

from .models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric


class TargetsFlowTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()
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

    def test_month_targets_can_be_deleted(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)

        self.client.get(reverse("target_month_settings"))
        un_amount_metric = TargetMetric.objects.get(department__code="UN", code="amount")
        MonthTargetMetricValue.objects.create(
            department=Department.objects.get(code="UN"),
            target_month=current_month,
            metric=un_amount_metric,
            value=12345,
            status="active",
        )
        self.assertTrue(MonthTargetMetricValue.objects.filter(target_month=current_month).exists())

        response = self.client.post(
            reverse("target_month_settings"),
            {
                "action": "delete_month_targets",
                "delete_month": current_month.strftime("%Y-%m"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MonthTargetMetricValue.objects.filter(target_month=current_month).exists())

    def test_unsaved_selected_month_is_not_shown_in_saved_month_history(self):
        today = timezone.localdate()
        target_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)

        response = self.client.get(
            reverse("target_month_settings") + f"?month={target_month.strftime('%Y-%m')}"
        )
        self.assertEqual(response.status_code, 200)
        history_months = [row["month"] for row in response.context["history_rows"]]
        self.assertNotIn(target_month, history_months)

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

    def test_period_save_rejects_overlapping_range(self):
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
                "end_date": (today + timedelta(days=3)).isoformat(),
            },
        )
        self.assertEqual(first.status_code, 200)
        before_count = Period.objects.count()

        second = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "2",
                "start_date": (today + timedelta(days=2)).isoformat(),
                "end_date": (today + timedelta(days=4)).isoformat(),
            },
        )
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "期間が既存の路程と重複しています。")
        self.assertEqual(Period.objects.count(), before_count)
