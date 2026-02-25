from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric


def seed_departments():
    return {
        "UN": Department.objects.create(name="UN", code="UN"),
        "WV": Department.objects.create(name="WV", code="WV"),
        "STYLE1": Department.objects.create(name="Style1", code="STYLE1"),
        "STYLE2": Department.objects.create(name="Style2", code="STYLE2"),
    }


class MemberSettingsViewTests(TestCase):
    def setUp(self):
        self.depts = seed_departments()
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_register_member_creates_record(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "Test Member",
            },
        )
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(name="Test Member")
        self.assertTrue(member.login_id.startswith("test-member"))

    def test_edit_member_updates_name(self):
        member = Member.objects.create(name="Old Name", login_id="old", password="")
        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "New Name",
            },
        )
        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.name, "New Name")
        self.assertEqual(member.login_id, "old")

    def test_delete_member_removes_record(self):
        member = Member.objects.create(name="Delete User", login_id="del_id", password="")
        response = self.client.post(reverse("member_delete", args=[member.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Member.objects.filter(id=member.id).exists())

    def test_register_member_with_departments_creates_links(self):
        response = self.client.post(
            reverse("member_settings"),
            {
                "name": "Dept User",
                "departments": [self.depts["UN"].id, self.depts["STYLE1"].id],
            },
        )
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(name="Dept User")
        self.assertEqual(
            set(member.department_links.values_list("department_id", flat=True)),
            {self.depts["UN"].id, self.depts["STYLE1"].id},
        )

    def test_edit_member_updates_departments(self):
        member = Member.objects.create(name="Move User", login_id="move_user", password="")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])
        response = self.client.post(
            reverse("member_settings"),
            {
                "edit_member_id": str(member.id),
                "name": "Move User",
                "departments": [self.depts["WV"].id],
            },
        )
        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(
            set(member.department_links.values_list("department_id", flat=True)),
            {self.depts["WV"].id},
        )

    def test_member_list_shows_department_name(self):
        member = Member.objects.create(name="Show User", login_id="show_user", password="")
        MemberDepartment.objects.create(member=member, department=self.depts["UN"])
        response = self.client.get(reverse("member_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN")


class DepartmentSettingsViewTests(TestCase):
    def setUp(self):
        self.depts = seed_departments()
        self.member_un = Member.objects.create(name="UN Leader", login_id="un_leader", password="")
        self.member_wv = Member.objects.create(name="WV Leader", login_id="wv_leader", password="")
        MemberDepartment.objects.create(member=self.member_un, department=self.depts["UN"])
        MemberDepartment.objects.create(member=self.member_wv, department=self.depts["WV"])
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_create_department(self):
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_department",
                "name": "New Team",
                "code": "NEWTEAM",
                "default_reporter": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Department.objects.filter(code="NEWTEAM", name="New Team").exists())

    def test_update_department_with_default_reporter(self):
        department = self.depts["UN"]
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_department",
                "edit_department_id": str(department.id),
                "name": "UN Updated",
                "code": "UN",
                "default_reporter": str(self.member_un.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        department.refresh_from_db()
        self.assertEqual(department.name, "UN Updated")
        self.assertEqual(department.default_reporter_id, self.member_un.id)

    def test_update_department_rejects_reporter_outside_department(self):
        department = self.depts["UN"]
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_department",
                "edit_department_id": str(department.id),
                "name": "UN Updated",
                "code": "UN",
                "default_reporter": str(self.member_wv.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        department.refresh_from_db()
        self.assertNotEqual(department.default_reporter_id, self.member_wv.id)

    def test_delete_department(self):
        department = Department.objects.create(name="To Delete", code="DEL_TEAM")
        response = self.client.post(reverse("department_delete", args=[department.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Department.objects.filter(id=department.id).exists())

    def test_create_metric_for_department(self):
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_metric",
                "metric_department_id": str(self.depts["UN"].id),
                "label": "Contracts",
                "code": "contracts",
                "unit": "item",
                "display_order": "1",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            TargetMetric.objects.filter(
                department=self.depts["UN"],
                code="contracts",
                label="Contracts",
            ).exists()
        )

    def test_update_metric(self):
        metric = TargetMetric.objects.create(
            department=self.depts["UN"],
            code="amount_extra",
            label="Amount Extra",
            unit="yen",
            display_order=3,
            is_active=True,
        )
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "save_metric",
                "metric_department_id": str(self.depts["UN"].id),
                "edit_metric_id": str(metric.id),
                "label": "Amount Updated",
                "code": "amount_extra",
                "unit": "yen",
                "display_order": "5",
            },
        )
        self.assertEqual(response.status_code, 200)
        metric.refresh_from_db()
        self.assertEqual(metric.label, "Amount Updated")
        self.assertEqual(metric.display_order, 5)

    def test_toggle_metric_active_state(self):
        metric = TargetMetric.objects.create(
            department=self.depts["UN"],
            code="toggle_target",
            label="Toggle Target",
            unit="item",
            display_order=4,
            is_active=True,
        )
        response = self.client.post(
            reverse("department_settings"),
            {
                "action": "toggle_metric",
                "metric_id": str(metric.id),
            },
        )
        self.assertEqual(response.status_code, 200)
        metric.refresh_from_db()
        self.assertFalse(metric.is_active)


class DashboardTargetAndMailIntegrationTests(TestCase):
    def setUp(self):
        self.depts = seed_departments()
        self.reporter = Member.objects.create(name="Alice", login_id="alice_mail", password="")
        MemberDepartment.objects.create(member=self.reporter, department=self.depts["UN"])
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_dashboard_target_progress_reflects_saved_targets_and_actuals(self):
        today = timezone.localdate()
        month = today.replace(day=1)
        period = Period.objects.create(
            month=month,
            name=f"{today.year}年度{today.month}月 第1次路程",
            status="active",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        metric = TargetMetric.objects.create(
            department=self.depts["UN"],
            code="amount",
            label="Amount",
            unit="yen",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=self.depts["UN"],
            target_month=month,
            metric=metric,
            status="active",
            value=2000,
        )
        PeriodTargetMetricValue.objects.create(
            period=period,
            department=self.depts["UN"],
            metric=metric,
            value=4000,
        )
        report = DailyDepartmentReport.objects.create(
            department=self.depts["UN"],
            report_date=today,
            reporter=self.reporter,
            total_count=1,
            followup_count=1000,
        )
        DailyDepartmentReportLine.objects.create(
            report=report,
            member=self.reporter,
            amount=1000,
            count=1,
        )

        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.context["target_progress_rows"] if r["label"] == "UN")
        self.assertIn("2000", row["month_target"])
        self.assertIn("1000", row["month_actual"])
        self.assertIn("50.0%", row["month_rate"])
        self.assertIn("4000", row["period_target"])
        self.assertIn("25.0%", row["period_rate"])

    def test_dashboard_mail_payload_switches_today_and_previous_day(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        report_today = DailyDepartmentReport.objects.create(
            department=self.depts["UN"],
            report_date=today,
            reporter=self.reporter,
            total_count=2,
            followup_count=3000,
        )
        DailyDepartmentReportLine.objects.create(
            report=report_today,
            member=self.reporter,
            amount=3000,
            count=2,
        )
        report_prev = DailyDepartmentReport.objects.create(
            department=self.depts["UN"],
            report_date=yesterday,
            reporter=self.reporter,
            total_count=1,
            followup_count=1000,
        )
        DailyDepartmentReportLine.objects.create(
            report=report_prev,
            member=self.reporter,
            amount=1000,
            count=1,
        )

        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 200)
        payload_map = response.context["mail_template_payload_map"]
        self.assertIn("today", payload_map)
        self.assertIn("prev", payload_map)

        today_section = next(s for s in payload_map["today"]["sections"] if s["code"] == "UN")
        prev_section = next(s for s in payload_map["prev"]["sections"] if s["code"] == "UN")
        self.assertEqual(today_section["daily_count"], 2)
        self.assertEqual(prev_section["daily_count"], 1)

    def test_dashboard_reflects_wv_and_style_reports_into_kpi_and_targets(self):
        today = timezone.localdate()
        month = today.replace(day=1)
        period = Period.objects.create(
            month=month,
            name=f"{today.year}年度{today.month}月 第2次路程",
            status="active",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )

        wv_member = Member.objects.create(name="WV User", login_id="wv_user_dash", password="")
        style_member = Member.objects.create(name="Style User", login_id="style_user_dash", password="")
        MemberDepartment.objects.create(member=wv_member, department=self.depts["WV"])
        MemberDepartment.objects.create(member=style_member, department=self.depts["STYLE1"])

        wv_cs = TargetMetric.objects.create(
            department=self.depts["WV"],
            code="cs_count",
            label="CS",
            unit="count",
            display_order=1,
            is_active=True,
        )
        wv_ref = TargetMetric.objects.create(
            department=self.depts["WV"],
            code="refugee_count",
            label="Ref",
            unit="count",
            display_order=2,
            is_active=True,
        )
        style_amount = TargetMetric.objects.create(
            department=self.depts["STYLE1"],
            code="amount",
            label="Amount",
            unit="yen",
            display_order=1,
            is_active=True,
        )

        MonthTargetMetricValue.objects.create(
            department=self.depts["WV"],
            target_month=month,
            metric=wv_cs,
            status="active",
            value=10,
        )
        MonthTargetMetricValue.objects.create(
            department=self.depts["WV"],
            target_month=month,
            metric=wv_ref,
            status="active",
            value=20,
        )
        MonthTargetMetricValue.objects.create(
            department=self.depts["STYLE1"],
            target_month=month,
            metric=style_amount,
            status="active",
            value=10000,
        )
        PeriodTargetMetricValue.objects.create(period=period, department=self.depts["WV"], metric=wv_cs, value=10)
        PeriodTargetMetricValue.objects.create(period=period, department=self.depts["WV"], metric=wv_ref, value=20)
        PeriodTargetMetricValue.objects.create(
            period=period,
            department=self.depts["STYLE1"],
            metric=style_amount,
            value=10000,
        )

        wv_report = DailyDepartmentReport.objects.create(
            department=self.depts["WV"],
            report_date=today,
            reporter=wv_member,
            total_count=3,
            followup_count=5000,
        )
        DailyDepartmentReportLine.objects.create(
            report=wv_report,
            member=wv_member,
            amount=5000,
            count=3,
            cs_count=1,
            refugee_count=2,
        )
        style_report = DailyDepartmentReport.objects.create(
            department=self.depts["STYLE1"],
            report_date=today,
            reporter=style_member,
            total_count=2,
            followup_count=8000,
        )
        DailyDepartmentReportLine.objects.create(
            report=style_report,
            member=style_member,
            amount=8000,
            count=2,
        )

        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 200)

        wv_card = next(card for card in response.context["kpi_cards"] if card["code"] == "WV")
        self.assertEqual(wv_card["cs_count"], 1)
        self.assertEqual(wv_card["refugee_count"], 2)
        self.assertEqual(wv_card["amount"], 5000)

        style_card = next(card for card in response.context["kpi_cards"] if card["code"] == "STYLE1")
        self.assertEqual(style_card["amount"], 8000)

        wv_progress = next(row for row in response.context["target_progress_rows"] if row["label"] == "WV")
        self.assertIn("10", wv_progress["month_target"])
        self.assertIn("20", wv_progress["month_target"])
        self.assertIn("1", wv_progress["month_actual"])
        self.assertIn("2", wv_progress["month_actual"])

        style_progress = next(row for row in response.context["target_progress_rows"] if row["label"] == "Style1")
        self.assertIn("10000", style_progress["month_target"])
        self.assertIn("8000", style_progress["month_actual"])

    def test_dashboard_month_target_uses_current_month_without_fallback(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        old_month = (current_month - timedelta(days=1)).replace(day=1)

        metric = TargetMetric.objects.create(
            department=self.depts["UN"],
            code="amount_old_only",
            label="Amount",
            unit="yen",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=self.depts["UN"],
            target_month=old_month,
            metric=metric,
            status="finished",
            value=9999,
        )

        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["target_month_summary"],
            f"{current_month.year}/{current_month.month}",
        )
        row = next(r for r in response.context["target_progress_rows"] if r["label"] == "UN")
        self.assertNotIn("9999", row["month_target"])

    def test_dashboard_reflects_existing_actuals_when_target_created_later(self):
        today = timezone.localdate()
        month = today.replace(day=1)
        period = Period.objects.create(
            month=month,
            name=f"{today.year}年度{today.month}月 第3次路程",
            status="active",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=2),
        )
        report = DailyDepartmentReport.objects.create(
            department=self.depts["UN"],
            report_date=today,
            reporter=self.reporter,
            total_count=2,
            followup_count=3000,
        )
        DailyDepartmentReportLine.objects.create(
            report=report,
            member=self.reporter,
            amount=3000,
            count=2,
        )

        metric = TargetMetric.objects.create(
            department=self.depts["UN"],
            code="amount",
            label="Amount",
            unit="yen",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=self.depts["UN"],
            target_month=month,
            metric=metric,
            status="active",
            value=6000,
        )
        PeriodTargetMetricValue.objects.create(
            period=period,
            department=self.depts["UN"],
            metric=metric,
            value=6000,
        )

        response = self.client.get(reverse("dashboard_index"))
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.context["target_progress_rows"] if r["label"] == "UN")
        self.assertIn("3000", row["month_actual"])
        self.assertIn("50.0%", row["month_rate"])
        self.assertIn("3000", row["period_actual"])
        self.assertIn("50.0%", row["period_rate"])
