from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department

from . import views as target_views
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

    def test_period_save_with_auto_status(self):
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
        period = Period.objects.get(month=current_month)
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
        period = Period.objects.get(month=current_month)
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

    def test_period_form_defaults_to_create_mode_without_edit_id(self):
        response = self.client.get(reverse("target_period_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form_edit_period_id"], "")

    def test_period_save_creates_multiple_periods_when_sequence_differs(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)

        self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": (today + timedelta(days=1)).isoformat(),
                "end_date": (today + timedelta(days=2)).isoformat(),
                "edit_period_id": "",
            },
        )
        self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "2",
                "start_date": (today + timedelta(days=3)).isoformat(),
                "end_date": (today + timedelta(days=4)).isoformat(),
                "edit_period_id": "",
            },
        )

        self.assertEqual(Period.objects.filter(month=current_month).count(), 2)

    def test_period_duplicate_save_requires_force_overwrite(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)

        self.client.get(reverse("target_period_settings"))
        first_response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": (today + timedelta(days=1)).isoformat(),
                "end_date": (today + timedelta(days=2)).isoformat(),
            },
        )
        self.assertEqual(first_response.status_code, 200)
        period = Period.objects.get(month=current_month)

        blocked_response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": (today - timedelta(days=2)).isoformat(),
                "end_date": (today - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(blocked_response.status_code, 200)
        self.assertEqual(Period.objects.filter(month=current_month).count(), 1)
        period.refresh_from_db()
        self.assertEqual(period.start_date, today + timedelta(days=1))
        self.assertEqual(period.end_date, today + timedelta(days=2))

        overwrite_response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": (today - timedelta(days=2)).isoformat(),
                "end_date": (today - timedelta(days=1)).isoformat(),
                "force_overwrite": "1",
                "overwrite_period_id": str(period.id),
            },
        )
        self.assertEqual(overwrite_response.status_code, 200)

        period.refresh_from_db()
        self.assertEqual(period.status, "finished")

    def test_period_save_rejects_overlapping_range(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)

        self.client.get(reverse("target_period_settings"))
        self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "1",
                "start_date": (today + timedelta(days=1)).isoformat(),
                "end_date": (today + timedelta(days=3)).isoformat(),
            },
        )
        before_count = Period.objects.count()

        response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "2",
                "start_date": (today + timedelta(days=2)).isoformat(),
                "end_date": (today + timedelta(days=4)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Period.objects.count(), before_count)

    def test_period_overlap_can_overwrite_when_forced(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        first = Period.objects.create(
            month=current_month,
            name=f"{today.year}年度{today.month}月 第1次路程",
            status="planned",
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=3),
        )

        response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "save_period",
                "period_month": current_month.strftime("%Y-%m"),
                "period_sequence": "2",
                "start_date": (today + timedelta(days=2)).isoformat(),
                "end_date": (today + timedelta(days=4)).isoformat(),
                "force_overwrite": "1",
                "overwrite_period_id": str(first.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Period.objects.count(), 1)
        first.refresh_from_db()
        self.assertIn("第2次路程", first.name)
        self.assertEqual(first.start_date, today + timedelta(days=2))
        self.assertEqual(first.end_date, today + timedelta(days=4))

    def test_period_can_be_deleted(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        period = Period.objects.create(
            month=current_month,
            name=f"{today.year}年度{today.month}月 第9次路程",
            status="active",
            start_date=today,
            end_date=today + timedelta(days=1),
        )

        response = self.client.post(
            reverse("target_period_settings"),
            {
                "action": "delete_period",
                "delete_period_id": str(period.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Period.objects.filter(id=period.id).exists())


class TargetStatusBoundaryTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()
        self.un = Department.objects.create(name="UN", code="UN")

    def _make_un_amount_metric(self):
        return TargetMetric.objects.create(
            department=self.un,
            code=f"amount_{TargetMetric.objects.count()}",
            label="Amount",
            unit="yen",
            display_order=1,
            is_active=True,
        )

    def test_month_status_switches_active_planned_finished(self):
        base_today = timezone.datetime(2026, 3, 15).date()
        self.assertEqual(
            target_views._month_status(timezone.datetime(2026, 3, 1).date(), today=base_today),
            "active",
        )
        self.assertEqual(
            target_views._month_status(timezone.datetime(2026, 2, 1).date(), today=base_today),
            "finished",
        )
        self.assertEqual(
            target_views._month_status(timezone.datetime(2026, 4, 1).date(), today=base_today),
            "planned",
        )

    def test_period_status_switches_active_planned_finished(self):
        base_today = timezone.datetime(2026, 3, 15).date()
        self.assertEqual(
            target_views._period_status(
                timezone.datetime(2026, 3, 10).date(),
                timezone.datetime(2026, 3, 20).date(),
                today=base_today,
            ),
            "active",
        )
        self.assertEqual(
            target_views._period_status(
                timezone.datetime(2026, 3, 16).date(),
                timezone.datetime(2026, 3, 20).date(),
                today=base_today,
            ),
            "planned",
        )
        self.assertEqual(
            target_views._period_status(
                timezone.datetime(2026, 3, 1).date(),
                timezone.datetime(2026, 3, 14).date(),
                today=base_today,
            ),
            "finished",
        )

    def test_current_month_prefers_today_month_when_exists(self):
        metric = self._make_un_amount_metric()
        current_month = timezone.datetime(2026, 3, 1).date()
        old_month = timezone.datetime(2026, 2, 1).date()
        MonthTargetMetricValue.objects.create(
            department=self.un,
            target_month=old_month,
            metric=metric,
            status="finished",
            value=1000,
        )
        MonthTargetMetricValue.objects.create(
            department=self.un,
            target_month=current_month,
            metric=metric,
            status="active",
            value=2000,
        )

        with patch("apps.targets.views.timezone.localdate", return_value=timezone.datetime(2026, 3, 15).date()):
            selected = target_views._current_month()
        self.assertEqual(selected, current_month)

    def test_current_month_does_not_fall_back_to_latest_saved_month(self):
        metric = self._make_un_amount_metric()
        MonthTargetMetricValue.objects.create(
            department=self.un,
            target_month=timezone.datetime(2026, 1, 1).date(),
            metric=metric,
            status="finished",
            value=1000,
        )
        MonthTargetMetricValue.objects.create(
            department=self.un,
            target_month=timezone.datetime(2026, 2, 1).date(),
            metric=metric,
            status="finished",
            value=2000,
        )

        with patch("apps.targets.views.timezone.localdate", return_value=timezone.datetime(2026, 3, 15).date()):
            selected = target_views._current_month()
        self.assertEqual(selected, timezone.datetime(2026, 3, 1).date())

    def test_current_period_prefers_active_period(self):
        Period.objects.create(
            month=timezone.datetime(2026, 2, 1).date(),
            name="2026年度2月 第1次路程",
            status="finished",
            start_date=timezone.datetime(2026, 2, 1).date(),
            end_date=timezone.datetime(2026, 2, 10).date(),
        )
        active = Period.objects.create(
            month=timezone.datetime(2026, 3, 1).date(),
            name="2026年度3月 第1次路程",
            status="active",
            start_date=timezone.datetime(2026, 3, 10).date(),
            end_date=timezone.datetime(2026, 3, 20).date(),
        )

        with patch("apps.targets.views.timezone.localdate", return_value=timezone.datetime(2026, 3, 15).date()):
            selected = target_views._current_period()
        self.assertEqual(selected.id, active.id)

    def test_current_period_falls_back_to_latest_period(self):
        old = Period.objects.create(
            month=timezone.datetime(2026, 1, 1).date(),
            name="2026年度1月 第1次路程",
            status="finished",
            start_date=timezone.datetime(2026, 1, 1).date(),
            end_date=timezone.datetime(2026, 1, 5).date(),
        )
        latest = Period.objects.create(
            month=timezone.datetime(2026, 2, 1).date(),
            name="2026年度2月 第1次路程",
            status="finished",
            start_date=timezone.datetime(2026, 2, 1).date(),
            end_date=timezone.datetime(2026, 2, 5).date(),
        )

        with patch("apps.targets.views.timezone.localdate", return_value=timezone.datetime(2026, 3, 15).date()):
            selected = target_views._current_period()
        self.assertEqual(selected.id, latest.id)
        self.assertNotEqual(selected.id, old.id)


class TargetSeedCommandTests(TestCase):
    def test_seed_command_creates_defaults_only_when_empty(self):
        self.assertEqual(Department.objects.count(), 0)
        self.assertEqual(TargetMetric.objects.count(), 0)

        call_command("seed_default_departments_and_metrics_if_empty")

        self.assertEqual(
            set(Department.objects.values_list("code", flat=True)),
            {"UN", "WV", "STYLE1", "STYLE2"},
        )
        self.assertEqual(TargetMetric.objects.count(), 6)

    def test_seed_command_skips_when_existing_data_present(self):
        Department.objects.create(name="Custom", code="CUSTOM")

        call_command("seed_default_departments_and_metrics_if_empty")

        self.assertEqual(Department.objects.count(), 1)
        self.assertEqual(TargetMetric.objects.count(), 0)
