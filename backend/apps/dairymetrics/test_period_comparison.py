from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Member
from apps.dairymetrics.models import MemberDailyMetricEntry, MetricAdjustment
from apps.dairymetrics.services.period_comparison import _route_key, build_period_comparison
from apps.targets.models import DepartmentPeriodTarget, Period, PeriodTargetMetricValue, TargetMetric


class PeriodComparisonTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(code="UN", name="UN")
        self.other = Department.objects.create(code="UNW", name="UN関西")
        self.members = [Member.objects.create(name=f"member {i}") for i in range(2)]
        self.jan = self.period(1, 1, "第1次路程")
        self.feb = self.period(2, 1, "第１次路程")
        self.second = self.period(1, 4, "第2次路程")
        self.entry(date(2026, 1, 1), 1000)
        self.entry(date(2026, 1, 1), 0, member=self.members[1])
        self.entry(date(2026, 1, 2), 3000)
        self.entry(date(2026, 2, 1), 6000)
        self.entry(date(2026, 1, 4), 5000)
        self.entry(date(2026, 1, 1), 999999, department=self.other)
        MetricAdjustment.objects.create(
            department=self.department, member=self.members[0],
            target_date=date(2026, 1, 1), source_type="increase", support_amount=90000,
        )
        metric = TargetMetric.objects.create(department=self.department, code="amount", label="金額", unit="円")
        PeriodTargetMetricValue.objects.create(period=self.jan, department=self.department, metric=metric, value=12000)
        DepartmentPeriodTarget.objects.create(period=self.feb, department=self.department, target_amount=8000)

    def period(self, month, start_day, name, status="finished"):
        return Period.objects.create(
            month=date(2026, month, 1), name=name, status=status,
            start_date=date(2026, month, start_day), end_date=date(2026, month, start_day + 2),
        )

    def entry(self, day, amount, member=None, department=None, **kwargs):
        return MemberDailyMetricEntry.objects.create(
            department=department or self.department, member=member or self.members[0],
            entry_date=day, support_amount=amount, result_count=int(amount > 0),
            approach_count=10, communication_count=5, **kwargs,
        )

    def build(self, department=None, **kwargs):
        return build_period_comparison(
            department=department or self.department, reference_date=date(2026, 3, 31), **kwargs,
        )

    def test_grouping_weights_counts_and_targets_use_normal_department_entries(self):
        with self.assertNumQueries(4):
            data = self.build()
        self.assertEqual([c["label"] for c in data["columns"]], ["第1次路程", "第2次路程"])
        rows = {row["label"]: row["values"] for row in data["rows"]}
        self.assertEqual(rows["通常実績金額"], ["10,000円", "5,000円"])
        self.assertEqual(rows["対象路程数"], ["2路程", "1路程"])
        self.assertEqual(rows["稼働日合計"], ["3日", "1日"])
        self.assertEqual(rows["延べ稼働人数"], ["4人日", "1人日"])
        self.assertEqual(rows["稼働メンバー実人数"], ["2人", "1人"])
        self.assertEqual(rows["稼働メンバー1人あたりの平均金額"][0], "2,500円")
        self.assertEqual(rows["目標進捗"][0], "50.0%")

    def test_excludes_planned_incomplete_and_out_of_range_periods(self):
        self.period(2, 4, "第3次路程", status="planned")
        self.entry(date(2026, 2, 4), 90000)
        future = self.period(4, 1, "第4次路程")
        self.entry(future.start_date, 90000)
        data = self.build(months=3)
        self.assertEqual(len(data["columns"]), 2)
        # January is outside the last three months ending in April.
        data = build_period_comparison(department=self.department, reference_date=date(2026, 4, 1), months=3)
        self.assertEqual(data["columns"][0]["values"][1], "6,000円")
        self.assertEqual(len(data["columns"]), 1)

    def test_all_department_types_and_wv_counts(self):
        for code in ["UNW", "WV", "STYLE2"]:
            department, _ = Department.objects.get_or_create(code=code, defaults={"name": code})
            if code != "UNW":
                self.entry(date(2026, 1, 1), 5000, department=department, cs_count=1, refugee_count=2)
            data = self.build(department)
            rows = {r["label"]: r["values"] for r in data["rows"]}
            self.assertEqual(rows["通常実績金額"][0], "999,999円" if code == "UNW" else "5,000円")
            if code == "WV":
                self.assertEqual(rows["通常実績件数"][0], "3件")
                self.assertEqual(rows["CS件数"][0], "1件")
                self.assertEqual(rows["難民件数"][0], "2件")

    def test_empty_department_and_normalized_ordinals(self):
        empty = Department.objects.create(code="EMPTY", name="empty")
        self.assertEqual(self.build(empty)["columns"], [])
        self.assertEqual(_route_key("2026年1月 第 十一次 路程"), ((0, 11), "第11次路程"))
        self.assertEqual(_route_key("特別路程"), ((1, "特別路程"), "特別路程"))

    def test_zero_payment_work_is_included_and_today_is_not_completed(self):
        empty = Department.objects.create(code="ZERO", name="zero")
        self.entry(date(2026, 1, 1), 0, department=empty)
        rows = {row["label"]: row["values"] for row in self.build(empty)["rows"]}
        self.assertEqual(rows["通常実績金額"], ["0円"])
        self.assertEqual(rows["延べ稼働人数"], ["1人日"])
        self.assertEqual(rows["稼働メンバー1人あたりの平均金額"], ["0円"])
        with patch("django.utils.timezone.localdate", return_value=self.jan.end_date):
            self.assertEqual(self.build(empty)["columns"], [])

    def test_view_keeps_scope_and_validates_comparison_months(self):
        self.client.force_login(get_user_model().objects.create_user("comparison-admin", is_staff=True))
        response = self.client.get(reverse("dairymetrics_metrics_v2_demo"), {
            "department": "UN", "scope": "custom", "start_date": "2026-01-01",
            "end_date": "2026-03-31", "compare_months": "invalid",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period_comparison"]["months"], 6)
        self.assertContains(response, "路程ごとの実績比較")
        self.assertContains(response, 'name="department" value="UN"')
        self.assertContains(response, 'name="start_date" value="2026-01-01"')
