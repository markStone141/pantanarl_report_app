from datetime import date, timedelta
from urllib.parse import parse_qs

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.common.test_helpers import AppTestMixin
from .models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MetricAdjustment


class CustomPeriodReportTests(AppTestMixin, TestCase):
    def setUp(self):
        self.department = self.create_department("UNW", name="UN関西")
        self.user, self.member = self.create_member_user(
            username="custom-report-member", name="関西メンバー", department=self.department,
        )
        self.login(self.user)
        self.query = {"department": "UNW", "scope": "custom", "start_date": "2026-01-30", "end_date": "2026-02-02"}
        for day, amount in [(date(2026, 1, 29), 90000), (date(2026, 1, 30), 1000),
                            (date(2026, 2, 2), 2000), (date(2026, 2, 3), 80000)]:
            MemberDailyMetricEntry.objects.create(
                member=self.member, department=self.department, entry_date=day,
                support_amount=amount, result_count=1, activity_closed=True,
            )
        for day, amount in [(date(2026, 2, 1), 500), (date(2026, 2, 3), 70000)]:
            MetricAdjustment.objects.create(
                member=self.member, department=self.department, target_date=day,
                source_type="increase", support_amount=amount, result_count=1,
            )
        for day in [date(2026, 1, 30), date(2026, 2, 2), date(2026, 2, 3)]:
            DepartmentDailyMetricSummary.objects.create(department=self.department, entry_date=day, daily_target_amount=5000)
        other = self.create_department("UN")
        MemberDailyMetricEntry.objects.create(member=self.member, department=other, entry_date=date(2026, 1, 30), support_amount=100000)

    def test_custom_report_includes_boundary_days_and_filters_department_and_adjustments(self):
        response = self.client.get(reverse("dairymetrics_metrics_report"), self.query)
        self.assertEqual(response.status_code, 200)
        scope = response.context["scope"]
        self.assertEqual((scope.start_date, scope.end_date), (date(2026, 1, 30), date(2026, 2, 2)))
        self.assertEqual(scope.scope, "custom")
        cards = {card["label"]: card["value"] for card in response.context["report"]["summary_cards"]}
        self.assertEqual(cards["合計支援金額"], "3,500円")
        self.assertContains(response, 'name="start_date" value="2026-01-30"')
        self.assertContains(response, 'name="end_date" value="2026-02-02"')
        self.assertEqual(len(response.context["report"]["adjustment_rows"]), 1)

    def test_export_links_and_formats_keep_exact_custom_period(self):
        response = self.client.get(reverse("dairymetrics_metrics_report"), self.query)
        query = {key: values[0] for key, values in parse_qs(response.context["report_export_query"]).items()}
        self.assertEqual(query["scope"], "custom")
        self.assertEqual(query["start_date"], self.query["start_date"])
        self.assertEqual(query["end_date"], self.query["end_date"])
        export_url = reverse("dairymetrics_metrics_report_export")
        response = self.client.get(export_url, {**query, "format": "json"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["report"]["start_date"], "2026-01-30")
        self.assertEqual(payload["report"]["end_date"], "2026-02-02")
        self.assertEqual(next(c["value"] for c in payload["summary"] if c["label"] == "合計支援金額"), "3,500円")
        response = self.client.get(export_url, {**query, "format": "txt"})
        self.assertContains(response, "対象期間: 2026-01-30 - 2026-02-02")
        self.assertContains(response, "3,500円")
        self.assertIn("20260130-20260202", response["Content-Disposition"])

    def test_reversed_dates_are_normalized_in_form_and_export(self):
        response = self.client.get(reverse("dairymetrics_metrics_report"), {
            **self.query, "start_date": "2026-02-02", "end_date": "2026-01-30",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date_value"], "2026-01-30")
        self.assertEqual(response.context["end_date_value"], "2026-02-02")

    def test_missing_or_invalid_dates_use_shared_recent_range_default(self):
        for values in [{}, {"start_date": "2026-02-31", "end_date": "invalid"}]:
            with self.subTest(values=values):
                response = self.client.get(reverse("dairymetrics_metrics_report"), {"scope": "custom", **values})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["scope"].start_date, timezone.localdate() - timedelta(days=29))
                self.assertEqual(response.context["scope"].end_date, timezone.localdate())

    def test_single_day_and_empty_range_are_supported(self):
        for day, expected in [("2026-01-30", "1,000円"), ("2025-01-01", "0円")]:
            response = self.client.get(reverse("dairymetrics_metrics_report"), {
                **self.query, "start_date": day, "end_date": day,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(next(c["value"] for c in response.context["report"]["summary_cards"]
                                  if c["label"] == "合計支援金額"), expected)
