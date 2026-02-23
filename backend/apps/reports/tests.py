from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine


class ReportMemberFilteringTests(TestCase):
    def test_report_un_shows_only_un_members(self):
        un = Department.objects.create(name="UN", code="UN")
        wv = Department.objects.create(name="WV", code="WV")
        un_member = Member.objects.create(name="UNメンバー", login_id="un_a", password="x")
        wv_member = Member.objects.create(name="WVメンバー", login_id="wv_a", password="y")
        MemberDepartment.objects.create(member=un_member, department=un)
        MemberDepartment.objects.create(member=wv_member, department=wv)

        response = self.client.get(reverse("report_un"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UNメンバー")
        self.assertNotContains(response, "WVメンバー")

    def test_report_un_marks_default_reporter_as_selected(self):
        un = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="責任者", login_id="leader_un", password="x")
        MemberDepartment.objects.create(member=reporter, department=un)
        un.default_reporter = reporter
        un.save(update_fields=["default_reporter"])

        response = self.client.get(reverse("report_un"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<option value="{reporter.id}" selected>{reporter.name}</option>',
            html=True,
        )


class ReportSubmitFlowTests(TestCase):
    def test_report_submit_saves_aggregates_and_lines(self):
        today_str = timezone.localdate().isoformat()
        department = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Alice", login_id="un_alice", password="x")
        member_2 = Member.objects.create(name="Bob", login_id="un_bob", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)
        MemberDepartment.objects.create(member=member_2, department=department)
        department.default_reporter = reporter
        department.save(update_fields=["default_reporter"])

        submit_response = self.client.post(
            reverse("report_un"),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "night shift",
                "member_ids": [str(reporter.id), str(member_2.id)],
                "amounts": ["3000", "5000"],
                "counts": ["1", "2"],
                "locations": ["Tokyo", "Yokohama"],
            },
        )

        self.assertEqual(submit_response.status_code, 302)
        self.assertEqual(DailyDepartmentReport.objects.count(), 1)
        report = DailyDepartmentReport.objects.first()
        self.assertEqual(report.total_count, 3)
        self.assertEqual(report.followup_count, 8000)
        self.assertEqual(DailyDepartmentReportLine.objects.count(), 2)

        history_response = self.client.get(reverse("report_history"))
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, "UN")
        self.assertContains(history_response, "Alice")
        self.assertContains(history_response, "night shift")
        self.assertContains(history_response, "8000")

    def test_report_history_page_shows_saved_report_and_lines(self):
        today_str = timezone.localdate().isoformat()
        department = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Alice", login_id="un_alice2", password="x")
        member_2 = Member.objects.create(name="Bob", login_id="un_bob2", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)
        MemberDepartment.objects.create(member=member_2, department=department)

        self.client.post(
            reverse("report_un"),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "history check",
                "member_ids": [str(reporter.id), str(member_2.id)],
                "amounts": ["1200", "2300"],
                "counts": ["1", "1"],
                "locations": ["Tokyo", "Saitama"],
            },
        )

        response = self.client.get(reverse("report_history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "保存報告一覧")
        self.assertContains(response, "history check")
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")

    def test_report_edit_updates_existing_report_and_lines(self):
        today_str = timezone.localdate().isoformat()
        department = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Alice", login_id="edit_alice", password="x")
        member_2 = Member.objects.create(name="Bob", login_id="edit_bob", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)
        MemberDepartment.objects.create(member=member_2, department=department)

        self.client.post(
            reverse("report_un"),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "before",
                "member_ids": [str(reporter.id)],
                "amounts": ["1000"],
                "counts": ["1"],
                "locations": ["Tokyo"],
            },
        )
        report = DailyDepartmentReport.objects.get()

        edit_response = self.client.post(
            reverse("report_edit", kwargs={"report_id": report.id}),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "after",
                "member_ids": [str(member_2.id)],
                "amounts": ["2500"],
                "counts": ["2"],
                "locations": ["Yokohama"],
            },
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertEqual(DailyDepartmentReport.objects.count(), 1)
        report.refresh_from_db()
        self.assertEqual(report.memo, "after")
        self.assertEqual(report.total_count, 2)
        self.assertEqual(report.followup_count, 2500)
        self.assertEqual(report.lines.count(), 1)
        self.assertEqual(report.lines.first().member_id, member_2.id)

    def test_report_edit_allows_past_report(self):
        department = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Alice", login_id="past_edit_alice", password="x")
        member_2 = Member.objects.create(name="Bob", login_id="past_edit_bob", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)
        MemberDepartment.objects.create(member=member_2, department=department)

        report = DailyDepartmentReport.objects.create(
            department=department,
            report_date=timezone.localdate() - timedelta(days=1),
            reporter=reporter,
            total_count=1,
            followup_count=1000,
            location="Tokyo",
            memo="old",
        )
        DailyDepartmentReportLine.objects.create(
            report=report,
            member=reporter,
            amount=1000,
            count=1,
            location="Tokyo",
        )

        edit_response = self.client.post(
            reverse("report_edit", kwargs={"report_id": report.id}),
            data={
                "report_date": report.report_date.isoformat(),
                "reporter": reporter.id,
                "memo": "old-fixed",
                "member_ids": [str(member_2.id)],
                "amounts": ["4000"],
                "counts": ["3"],
                "locations": ["Sendai"],
                "next": "report_history",
            },
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertEqual(edit_response.url, reverse("report_history"))
        report.refresh_from_db()
        self.assertEqual(report.memo, "old-fixed")
        self.assertEqual(report.total_count, 3)
        self.assertEqual(report.followup_count, 4000)
