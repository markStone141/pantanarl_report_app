from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.dairymetrics.models import MemberDailyMetricEntry, MetricAdjustment
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric
from .base import PerformanceTestBase


class IncreaseAdjustmentClassificationTests(PerformanceTestBase):
    def prepare_increase(self, *, normal_amount=3000, target=5000, code="UN"):
        if code != "UN":
            self.department.code = code
            self.department.save(update_fields=["code"])
        today = timezone.localdate()
        self.period = Period.objects.create(
            month=today.replace(day=1), name="検証路程", status="active",
            start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
        )
        metric = TargetMetric.objects.create(department=self.department, code="amount", label="金額", unit="円")
        MonthTargetMetricValue.objects.create(
            department=self.department, metric=metric, target_month=today.replace(day=1), value=target,
        )
        PeriodTargetMetricValue.objects.create(department=self.department, metric=metric, period=self.period, value=target)
        if normal_amount:
            MemberDailyMetricEntry.objects.create(
                member=self.member, department=self.department, entry_date=today,
                support_amount=normal_amount, result_count=1, activity_closed=True,
            )
        response = self.client.post(reverse("performance_adjustments"), {
            "source_type": "increase", "department": self.department.pk,
            "member": self.member.pk, "target_date": today.isoformat(),
            "location_name": "確認用現場", "amount_choice": "direct", "amount": "6200",
        })
        self.assertEqual(response.status_code, 302)
        record = MetricAdjustment.objects.get(member=self.member, department=self.department)
        self.assertEqual(record.support_amount, 6200)
        self.assertEqual(record.result_count, 1)
        self.assertEqual(record.source_type, "increase")

    def test_input_increase_is_counted_as_adjustment_in_total_and_member_summary(self):
        self.prepare_increase()
        response = self.client.get(reverse("performance_index"))
        self.assertEqual(response.status_code, 200)
        for key in ["month_progress_cards", "period_progress_cards"]:
            card = next(c for c in response.context["dashboard_snapshot"][key] if c["label"] == "UN")
            self.assertEqual(card["actual_amount"], 9200)
            self.assertEqual(card["base_actual_amount_text"], "3,000円")
            self.assertEqual(card["adjustment_amount_text"], "6,200円")
        response = self.client.get(reverse("performance_member_detail", args=[self.member.pk, self.department.pk]))
        summary = {item["key"]: item["value"] for item in response.context["recent_summary_items"]}
        self.assertEqual(summary["amount_total"], "9,200円")
        self.assertEqual(summary["count_total"], "2件")
        self.assertEqual(summary["adjustment_amount_total"], "6,200円")
        self.assertEqual(summary["adjustment_count_total"], "1件")
        self.assertEqual(response.context["activity_trend"]["adjustment_amounts"], [6200])

    def test_increase_is_not_hidden_in_chart_when_normal_already_reaches_target(self):
        self.prepare_increase(normal_amount=6000)
        response = self.client.get(reverse("performance_index"))
        for key in ["month_progress_cards", "period_progress_cards"]:
            card = next(c for c in response.context["dashboard_snapshot"][key] if c["label"] == "UN")
            self.assertEqual(card["chart_values"], [6000, 6200, 0])
            self.assertEqual(card["rate"], 244.0)

    def test_full_increase_is_shown_when_total_crosses_target(self):
        self.prepare_increase(code="UNW")
        response = self.client.get(reverse("performance_index"))
        card = next(c for c in response.context["dashboard_snapshot"]["month_progress_cards"] if c["label"] == "UNW")
        self.assertEqual(card["chart_values"], [3000, 6200, 0])
        self.assertEqual(card["actual_amount"], 9200)

    def test_adjustment_without_daily_entry_is_still_counted(self):
        self.prepare_increase(normal_amount=0, target=10000)
        response = self.client.get(reverse("performance_index"))
        card = next(c for c in response.context["dashboard_snapshot"]["month_progress_cards"] if c["label"] == "UN")
        self.assertEqual(card["chart_values"], [0, 6200, 3800])
        self.assertEqual(card["actual_amount"], 6200)
        self.assertEqual(card["base_actual_amount_text"], "0円")
