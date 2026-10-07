from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.dairymetrics.models import (
    MemberDailyMetricEntry, MemberMetricTransaction, MemberMonthMetricTarget, MemberPeriodMetricTarget,
)
from apps.dairymetrics.services.metrics_v2_ranking import ranking_metric_options_for_department
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric


class DepartmentSeparationTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("admin", is_staff=True))
        self.today = timezone.localdate()
        self.month = self.today.replace(day=1)
        self.period = Period.objects.create(
            month=self.month, name="第1次路程", status="active",
            start_date=self.today - timedelta(days=1), end_date=self.today + timedelta(days=1),
        )
        self.departments = []
        self.members = []
        self.metrics = []
        for code, name, amount in [("UN", "UN", 2000), ("UN_KANSAI", "UN関西", 7000)]:
            response = self.client.post(reverse("department_settings"), {
                "action": "save_department", "code": code, "name": name,
                "show_in_dashboard_submission": "on", "show_in_dashboard_progress": "on",
                "show_in_target_history": "on",
            })
            self.assertEqual(response.status_code, 200)
            department = Department.objects.get(code=code)
            member = Member.objects.create(name=f"{name}専属メンバー")
            MemberDepartment.objects.create(member=member, department=department)
            entry = MemberDailyMetricEntry.objects.create(
                member=member, department=department, entry_date=self.today,
                approach_count=10, communication_count=5, activity_closed=True,
            )
            MemberMetricTransaction.objects.create(entry=entry, support_amount=amount)
            report = DailyDepartmentReport.objects.create(
                department=department, reporter=member, report_date=self.today,
                total_count=1, followup_count=amount,
            )
            DailyDepartmentReportLine.objects.create(report=report, member=member, amount=amount, count=1)
            metric = TargetMetric.objects.create(
                department=department, code="amount", label="金額", unit="円",
            )
            self.departments.append(department)
            self.members.append(member)
            self.metrics.append(metric)
        self.save_targets()

    def save_targets(self):
        data = {f"metric_{metric.pk}": value for metric, value in zip(self.metrics, [20000, 70000])}
        response = self.client.post(reverse("target_month_settings"), {
            "action": "save_month_targets", "month": self.month.strftime("%Y-%m"), **data,
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("target_period_settings"), {
            "action": "save_period_targets", "selected_period_id": self.period.pk, **data,
        })
        self.assertEqual(response.status_code, 200)

    def query(self, department, scope):
        return {"department": department.code, "scope": scope,
                "month": self.month.strftime("%Y-%m"), "period_id": self.period.pk}

    def test_analysis_separates_members_amounts_and_keeps_un_rankings(self):
        for scope in ["month", "period"]:
            for index, department in enumerate(self.departments):
                with self.subTest(scope=scope, department=department.code):
                    response = self.client.get(reverse("dairymetrics_metrics_v2_demo"), self.query(department, scope))
                    self.assertEqual(response.status_code, 200)
                    payload = response.context["metrics_v2_payload"]
                    self.assertEqual(payload["overall_summary"]["totals"]["support_amount"], [2000, 7000][index])
                    ranking = payload["ranking"]["metric_map"]
                    self.assertEqual(ranking["support_amount"]["labels"], [self.members[index].name])
                    self.assertEqual(ranking["support_amount"]["values"], [[2000], [7000]][index])
                    self.assertEqual(
                        payload["ranking"]["options"], ranking_metric_options_for_department("UN")
                    )
                    self.assertGreater(ranking["amount_stability_score"]["values"][0], 0)

    def test_reflection_export_keeps_members_and_results_separate(self):
        for scope in ["month", "period"]:
            for index, department in enumerate(self.departments):
                with self.subTest(scope=scope, department=department.code):
                    response = self.client.get(reverse("dairymetrics_metrics_report"), self.query(department, scope))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, self.members[index].name)
                    self.assertNotContains(response, self.members[1-index].name)
                    export = self.client.get(reverse("dairymetrics_metrics_report_export"), {
                        **self.query(department, scope), "format": "json",
                    })
                    self.assertEqual(export.status_code, 200)
                    payload = export.json()
                    self.assertEqual(payload["report"]["department_code"], department.code)
                    self.assertEqual(len(payload["member_results"]), 1)
                    self.assertGreater(payload["member_results"][0]["amount_stability_score_value"], 0)
                    self.assertIn(self.members[index].name, str(payload["member_results"]))
                    self.assertNotIn(self.members[1-index].name, str(payload))

    def test_month_and_period_targets_are_saved_independently_via_ui(self):
        for index, department in enumerate(self.departments):
            metric = self.metrics[index]
            self.assertEqual(MonthTargetMetricValue.objects.get(
                department=department, metric=metric, target_month=self.month).value, [20000, 70000][index])
            self.assertEqual(PeriodTargetMetricValue.objects.get(
                department=department, metric=metric, period=self.period).value, [20000, 70000][index])
        data = {f"metric_{self.metrics[0].pk}": 20000, f"metric_{self.metrics[1].pk}": 90000}
        self.client.post(reverse("target_month_settings"), {
            "action": "save_month_targets", "month": self.month.strftime("%Y-%m"), **data,
        })
        self.assertEqual(MonthTargetMetricValue.objects.get(department=self.departments[0], metric=self.metrics[0]).value, 20000)
        self.assertEqual(MonthTargetMetricValue.objects.get(department=self.departments[1], metric=self.metrics[1]).value, 90000)
        self.assertEqual(PeriodTargetMetricValue.objects.get(department=self.departments[1], metric=self.metrics[1]).value, 70000)

    def test_mail_template_has_independent_department_members_and_targets(self):
        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 200)
        sections = {s["code"]: s for s in response.context["mail_template_payload_map"]["today"]["sections"]}
        for index, department in enumerate(self.departments):
            section = sections[department.code]
            self.assertEqual(section["name"], department.name)
            self.assertTrue(section["has_report"])
            self.assertEqual([m["name"] for m in section["member_lines"]], [self.members[index].name])
            self.assertEqual(section["daily_amount_text"], ["2,000円", "7,000円"][index])
            self.assertIn(["20,000円", "70,000円"][index], str(section["month_lines"]))
            self.assertIn(["20,000円", "70,000円"][index], str(section["period_lines"]))
        self.assertEqual(sections["UN_KANSAI"]["heading"], "UN関西")

    def test_hidden_department_is_excluded_from_mail(self):
        department = self.departments[1]
        department.show_in_dashboard_submission = False
        department.save()
        response = self.client.get(reverse("dashboard_index"))
        self.assertTrue(response.context["kpi_cards"])
        self.assertIn(department.code, [card["code"] for card in response.context["kpi_cards"]])
        for payload in response.context["mail_template_payload_map"].values():
            self.assertNotIn(department.code, [s["code"] for s in payload["sections"]])
            self.assertIn("UN", [s["code"] for s in payload["sections"]])

    def test_member_in_both_departments_has_separate_personal_targets_and_actuals(self):
        member = self.members[0]
        kansai = self.departments[1]
        MemberDepartment.objects.create(member=member, department=kansai)
        entry = MemberDailyMetricEntry.objects.create(
            member=member, department=kansai, entry_date=self.today,
            approach_count=10, communication_count=5, activity_closed=True,
        )
        MemberMetricTransaction.objects.create(entry=entry, support_amount=3000)
        for index, department in enumerate(self.departments):
            MemberMonthMetricTarget.objects.create(
                member=member, department=department, target_month=self.month,
                target_amount=[40000, 30000][index],
            )
            MemberPeriodMetricTarget.objects.create(
                member=member, department=department, period=self.period,
                target_amount=[40000, 30000][index],
            )
            for scope in ["month", "period"]:
                response = self.client.get(reverse("dairymetrics_metrics_v2_demo"), {
                    **self.query(department, scope), "member": member.pk,
                })
                self.assertEqual(response.status_code, 200)
                summary = response.context["metrics_v2_payload"]["personal_summary"]
                self.assertEqual(summary["totals"]["support_amount"], [2000, 3000][index])
                progress = next(row for row in summary["averages"] if row["label"] == "目標進捗")
                self.assertEqual(progress["value"], ["5.0%", "10.0%"][index])
