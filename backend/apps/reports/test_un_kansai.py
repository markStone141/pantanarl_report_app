from importlib import import_module

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine


class UnKansaiReportTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()
        self.style = Department.objects.create(code="STYLE1", name="Style1")
        self.legacy = DailyDepartmentReport.objects.create(
            department=self.style, memo="Style1 過去報告", total_count=3
        )
        self.line = DailyDepartmentReportLine.objects.create(
            report=self.legacy, amount=1200, count=3
        )
        migration = import_module("apps.accounts.migrations.0014_add_un_kansai")
        editor = connection.schema_editor()
        migration.add_un_kansai(apps, editor)
        migration.add_un_kansai(apps, editor)
        self.kansai = Department.objects.get(code="UN_KANSAI")

    def test_entry_replaces_style1_and_keeps_history_and_edit(self):
        response = self.client.get(reverse("report_index"))
        self.assertContains(response, "UN関西 報告へ")
        self.assertContains(response, reverse("report_un_kansai"))
        self.assertNotContains(response, reverse("report_style1"))
        history = self.client.get(reverse("report_history"))
        self.assertContains(history, "Style1")
        edit = self.client.get(reverse("report_edit", args=[self.legacy.pk]))
        self.assertEqual(edit.status_code, 200)
        self.assertContains(edit, "Style1 報告フォーム")
        self.legacy.refresh_from_db()
        self.line.refresh_from_db()
        self.assertEqual(self.legacy.department_id, self.style.pk)
        self.assertEqual(self.legacy.total_count, 3)
        self.assertEqual(self.line.amount, 1200)
        self.assertEqual(Department.objects.filter(code="UN_KANSAI").count(), 1)

    def test_new_report_saves_separately_and_filters_members(self):
        member = Member.objects.create(name="関西メンバー")
        MemberDepartment.objects.create(member=member, department=self.kansai)
        old_member = Member.objects.create(name="Styleメンバー")
        MemberDepartment.objects.create(member=old_member, department=self.style)
        response = self.client.get(reverse("report_un_kansai"))
        self.assertContains(response, "UN関西 報告フォーム")
        self.assertContains(response, member.name)
        self.assertNotContains(response, old_member.name)
        response = self.client.post(reverse("report_un_kansai"), {
            "report_date": timezone.localdate().isoformat(),
            "reporter": member.pk, "memo": "関西新規報告",
            "member_ids": [str(member.pk)], "amounts": ["2000"],
            "counts": ["2"],
        })
        self.assertEqual(response.status_code, 302)
        report = DailyDepartmentReport.objects.get(department=self.kansai)
        self.assertEqual(report.total_count, 2)
        self.assertEqual(report.lines.get().amount, 2000)
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.memo, "Style1 過去報告")
        self.assertTrue(DailyDepartmentReportLine.objects.filter(pk=self.line.pk).exists())

    def test_hidden_kansai_has_no_entry_and_redirects(self):
        self.kansai.show_in_dashboard_submission = False
        self.kansai.save()
        self.assertNotContains(self.client.get(reverse("report_index")), "UN関西 報告へ")
        self.assertRedirects(self.client.get(reverse("report_un_kansai")), reverse("report_index"))

    def test_anonymous_user_cannot_enter_kansai_report(self):
        self.client.session.flush()
        self.assertRedirects(self.client.get(reverse("report_un_kansai")), reverse("home"))
