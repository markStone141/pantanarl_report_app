from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine
from apps.targets.models import TargetMetric
from apps.targets.views import _department_configs


class UiDepartmentReportTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def add_department_via_ui(self, code="UN_KANSAI", name="UN関西"):
        response = self.client.post(reverse("department_settings"), {
            "action": "save_department", "code": code, "name": name,
            "show_in_dashboard_submission": "on",
            "show_in_dashboard_progress": "on", "show_in_target_history": "on",
        })
        self.assertEqual(response.status_code, 200)
        return Department.objects.get(code=code)

    def test_ui_replaces_entry_and_preserves_style_history_and_edit(self):
        style = self.add_department_via_ui("STYLE1", "Style1")
        legacy = DailyDepartmentReport.objects.create(department=style, memo="過去報告")
        line = DailyDepartmentReportLine.objects.create(report=legacy, amount=1200)
        self.add_department_via_ui()
        response = self.client.post(reverse("department_settings"), {
            "action": "save_department", "edit_department_id": str(style.pk),
            "code": style.code, "name": style.name,
            "show_in_dashboard_progress": "on", "show_in_target_history": "on",
        })
        self.assertEqual(response.status_code, 200)
        index = self.client.get(reverse("report_index"))
        self.assertContains(index, "UN関西 報告へ")
        self.assertNotContains(index, "Style1 報告へ")
        history = self.client.get(reverse("report_history"))
        self.assertContains(history, "Style1")
        self.assertIn(legacy, history.context["reports"])
        self.assertIn({"code": style.code, "name": style.name}, history.context["filter_departments"])
        edit = self.client.get(reverse("report_edit", args=[legacy.pk]))
        self.assertEqual(edit.status_code, 200)
        self.assertContains(edit, "Style1 報告フォーム")
        self.assertRedirects(self.client.get(reverse("report_style1")), reverse("report_index"))
        legacy.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(legacy.department_id, style.pk)
        self.assertEqual(legacy.memo, "過去報告")
        self.assertEqual(line.amount, 1200)

    def test_arbitrary_ui_department_can_submit_without_code_changes(self):
        department = self.add_department_via_ui("NEW_TEAM", "新部署")
        member = Member.objects.create(name="新部署メンバー")
        MemberDepartment.objects.create(member=member, department=department)
        outsider = Member.objects.create(name="別部署メンバー")
        url = reverse("report_department", kwargs={"dept_code": department.code})
        response = self.client.get(url)
        self.assertContains(response, "新部署 報告フォーム")
        self.assertContains(response, member.name)
        self.assertNotContains(response, outsider.name)
        response = self.client.post(url, {
            "report_date": timezone.localdate().isoformat(), "reporter": member.pk,
            "member_ids": [str(member.pk)], "amounts": ["2000"], "counts": ["2"],
        })
        self.assertEqual(response.status_code, 302)
        report = DailyDepartmentReport.objects.get(department=department)
        self.assertEqual(report.total_count, 2)
        self.assertEqual(report.lines.get().amount, 2000)
        history = self.client.get(reverse("report_history"))
        self.assertIn({"code": department.code, "name": department.name}, history.context["filter_departments"])

    def test_targets_use_ui_department_and_ui_metrics(self):
        department = self.add_department_via_ui()
        response = self.client.post(reverse("department_settings"), {
            "action": "save_metric", "metric_department_id": str(department.pk),
            "code": "count", "label": "獲得件数", "unit": "件",
            "display_order": "1", "is_active": "on",
        })
        self.assertEqual(response.status_code, 200)
        config = next(c for c in _department_configs() if c["department"] == department)
        self.assertEqual(config["label"], "UN関西")
        self.assertEqual([m.label for m in config["metrics"]], ["獲得件数"])
        self.assertContains(self.client.get(reverse("target_month_settings")), "獲得件数")
        self.assertEqual(TargetMetric.objects.filter(department=department).count(), 1)

    def test_pages_do_not_create_departments(self):
        self.client.get(reverse("report_index"))
        self.client.get(reverse("target_month_settings"))
        url = reverse("report_department", kwargs={"dept_code": "UN_KANSAI"})
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {}).status_code, 404)
        self.assertFalse(Department.objects.exists())

    def test_generic_route_enforces_auth_and_visibility(self):
        department = self.add_department_via_ui()
        department.show_in_dashboard_submission = False
        department.save()
        url = reverse("report_department", kwargs={"dept_code": department.code})
        self.assertRedirects(self.client.get(url), reverse("report_index"))
        self.client.session.flush()
        self.assertRedirects(self.client.get(url), reverse("home"))
