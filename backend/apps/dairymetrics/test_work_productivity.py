from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Department, Member
from apps.dairymetrics.models import MemberDailyMetricEntry, MemberMetricTransaction, MetricAdjustment
from apps.dairymetrics.services.work_productivity import build_normal_work_productivity
from apps.targets.models import Period


class NormalWorkProductivityTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(code="UNW", name="UN関西")
        self.members = [Member.objects.create(name=f"Member {i}") for i in range(3)]
        for member, amount in zip(self.members, [10000, 0, 0]):
            self.entry(member, date(2026, 1, 30), amount)
        self.entry(self.members[0], date(2026, 1, 31), 20000)
        self.entry(self.members[0], date(2026, 2, 1), 5000)

    def entry(self, member, day, amount, department=None):
        entry = MemberDailyMetricEntry.objects.create(
            department=department or self.department, member=member, entry_date=day,
        )
        if amount:
            MemberMetricTransaction.objects.create(entry=entry, support_amount=amount)
        return entry

    def build(self, start=date(2026, 1, 30), end=date(2026, 2, 1)):
        return build_normal_work_productivity(department=self.department, start_date=start, end_date=end)

    def test_weighted_daily_monthly_and_period_including_zero_workers(self):
        data = self.build()
        self.assertEqual([r["workers"] for r in data["daily"]], [3, 1, 1])
        self.assertEqual([r["average"] for r in data["daily"]], [3333.33, 20000, 5000])
        self.assertEqual([r["average"] for r in data["monthly"]], [7500, 5000])
        self.assertEqual(data["summary"]["average"], 7000)
        self.assertEqual(data["summary"]["workers"], 5)

    def test_excludes_adjustments_other_departments_and_dates(self):
        for source in ["increase", "qr", "postal"]:
            MetricAdjustment.objects.create(
                department=self.department, member=self.members[0], target_date=date(2026, 1, 30),
                source_type=source, support_amount=100000, return_qr_amount=100000,
                return_postal_amount=100000,
            )
        other = Department.objects.create(code="UN", name="UN")
        self.entry(self.members[0], date(2026, 1, 30), 900000, other)
        self.entry(self.members[0], date(2026, 1, 29), 900000)
        self.assertEqual(self.build()["summary"]["amount"], 35000)
        self.assertEqual(self.build(start=date(2026, 1, 31))["monthly"][0]["average"], 20000)

    def test_multiple_transactions_count_worker_once(self):
        entry = MemberDailyMetricEntry.objects.get(member=self.members[0], entry_date=date(2026, 1, 30))
        MemberMetricTransaction.objects.create(entry=entry, support_amount=5000)
        data = self.build(end=date(2026, 1, 30))
        self.assertEqual(data["summary"]["workers"], 3)
        self.assertEqual(data["summary"]["average"], 5000)

    def test_empty_period_and_zero_amount_are_distinct(self):
        data = self.build(start=date(2026, 3, 1), end=date(2026, 3, 31))
        self.assertIsNone(data["summary"]["average"])
        self.assertEqual(data["summary"]["average_text"], "—")
        self.assertEqual(data["daily"], [])
        self.entry(self.members[0], date(2026, 3, 1), 0)
        self.assertEqual(self.build(start=date(2026, 3, 1), end=date(2026, 3, 31))["summary"]["average"], 0)

    def test_custom_scope_view(self):
        self.client.force_login(get_user_model().objects.create_user("productivity-admin", is_staff=True))
        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"), {
            "department": "UNW", "scope": "custom", "start_date": "2026-01-30", "end_date": "2026-02-01",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="normal-work-productivity-mode"')
        self.assertEqual(response.context["metrics_v2_payload"]["normal_work_productivity"]["summary"]["average"], 7000)

    def test_reflection_report_scopes_use_same_productivity_payload(self):
        self.client.force_login(get_user_model().objects.create_user("report-admin", is_staff=True))
        period = Period.objects.create(
            month=date(2026, 1, 1), name="対象路程", status="active",
            start_date=date(2026, 1, 30), end_date=date(2026, 2, 1),
        )
        MetricAdjustment.objects.create(
            department=self.department, member=self.members[0], target_date=date(2026, 1, 30),
            source_type="increase", support_amount=90000,
        )
        queries = [
            ({"scope": "custom", "start_date": "2026-01-30", "end_date": "2026-02-01"}, 7000),
            ({"scope": "period", "period_id": period.pk}, 7000),
            ({"scope": "month", "month": "2026-01"}, 7500),
            ({"scope": "month", "month": "2026-03"}, None),
        ]
        for query, expected in queries:
            with self.subTest(query=query):
                response = self.client.get(reverse("dairymetrics_metrics_report"), {"department": "UNW", **query})
                self.assertEqual(response.status_code, 200)
                report = response.context["report"]
                self.assertEqual(report["normal_work_productivity"]["summary"]["average"], expected)
                self.assertEqual(report["normal_work_productivity"], report["analysis_chart_payload"]["normal_work_productivity"])
                self.assertContains(response, 'id="normal-work-productivity-mode"')
