from datetime import timedelta

from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.reports.models import DailyDepartmentReport, DailyDepartmentReportLine
from apps.targets.models import MonthTargetMetricValue, TargetMetric


class ReportMemberFilteringTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_report_un_shows_only_un_members(self):
        un = Department.objects.create(name="UN", code="UN")
        wv = Department.objects.create(name="WV", code="WV")
        un_member = Member.objects.create(name="UN member", login_id="un_a", password="x")
        wv_member = Member.objects.create(name="WV member", login_id="wv_a", password="y")
        MemberDepartment.objects.create(member=un_member, department=un)
        MemberDepartment.objects.create(member=wv_member, department=wv)

        response = self.client.get(reverse("report_un"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN member")
        self.assertNotContains(response, "WV member")

    def test_report_un_marks_default_reporter_as_selected(self):
        un = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Leader", login_id="leader_un", password="x")
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

    def test_report_index_uses_department_display_name_for_buttons(self):
        Department.objects.create(name="ユニセフ", code="UN")
        Department.objects.create(name="ワールドビジョン", code="WV")

        response = self.client.get(reverse("report_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ユニセフ 報告へ")
        self.assertContains(response, "ワールドビジョン 報告へ")

    def test_report_form_title_uses_department_display_name(self):
        department = Department.objects.create(name="ユニセフ渋谷", code="UN")
        reporter = Member.objects.create(name="Leader", login_id="leader_un_title", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)

        response = self.client.get(reverse("report_un"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ユニセフ渋谷 報告フォーム")
        self.assertContains(response, "(ユニセフ渋谷)")

    def test_style_form_hides_location_column(self):
        department = Department.objects.create(name="Style 港北", code="STYLE1")
        reporter = Member.objects.create(name="Leader", login_id="leader_style1", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)

        response = self.client.get(reverse("report_style1"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<th>現場</th>", html=True)
        self.assertNotContains(response, 'name="locations"')


class ReportSubmitFlowTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()

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
        self.assertContains(response, "history check")
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")

    def test_report_submit_overwrites_existing_same_day_same_department(self):
        today_str = timezone.localdate().isoformat()
        department = Department.objects.create(name="UN", code="UN")
        reporter_1 = Member.objects.create(name="Alice", login_id="overwrite_alice", password="x")
        reporter_2 = Member.objects.create(name="Bob", login_id="overwrite_bob", password="x")
        member_1 = Member.objects.create(name="Carol", login_id="overwrite_carol", password="x")
        member_2 = Member.objects.create(name="Dave", login_id="overwrite_dave", password="x")
        for member in (reporter_1, reporter_2, member_1, member_2):
            MemberDepartment.objects.create(member=member, department=department)

        first = DailyDepartmentReport.objects.create(
            department=department,
            report_date=timezone.localdate(),
            reporter=reporter_1,
            total_count=1,
            followup_count=1000,
            memo="old",
        )
        DailyDepartmentReportLine.objects.create(
            report=first,
            member=member_1,
            amount=1000,
            count=1,
            location="A",
        )

        second = DailyDepartmentReport.objects.create(
            department=department,
            report_date=timezone.localdate(),
            reporter=reporter_2,
            total_count=2,
            followup_count=2000,
            memo="old-2",
        )
        DailyDepartmentReportLine.objects.create(
            report=second,
            member=member_2,
            amount=2000,
            count=2,
            location="B",
        )

        submit_response = self.client.post(
            reverse("report_un"),
            data={
                "report_date": today_str,
                "reporter": reporter_1.id,
                "memo": "latest",
                "member_ids": [str(member_1.id)],
                "amounts": ["5000"],
                "counts": ["5"],
                "locations": ["Tokyo"],
            },
        )

        self.assertEqual(submit_response.status_code, 302)
        self.assertEqual(DailyDepartmentReport.objects.filter(department=department, report_date=timezone.localdate()).count(), 1)
        report = DailyDepartmentReport.objects.get(department=department, report_date=timezone.localdate())
        self.assertEqual(report.id, second.id)
        self.assertEqual(report.reporter_id, reporter_1.id)
        self.assertEqual(report.total_count, 5)
        self.assertEqual(report.followup_count, 5000)
        self.assertEqual(report.memo, "latest")
        self.assertEqual(report.lines.count(), 1)
        line = report.lines.first()
        self.assertEqual(line.member_id, member_1.id)
        self.assertEqual(line.amount, 5000)
        self.assertEqual(line.count, 5)

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

    def test_report_form_recent_history_shows_only_today(self):
        department = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Alice", login_id="today_only_alice", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)

        DailyDepartmentReport.objects.create(
            department=department,
            report_date=timezone.localdate() - timedelta(days=1),
            reporter=reporter,
            total_count=1,
            followup_count=1000,
            memo="yesterday-data",
        )
        DailyDepartmentReport.objects.create(
            department=department,
            report_date=timezone.localdate(),
            reporter=reporter,
            total_count=2,
            followup_count=2000,
            memo="today-data",
        )

        response = self.client.get(reverse("report_un"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "today-data")
        self.assertNotContains(response, "yesterday-data")

    def test_report_delete_removes_selected_report(self):
        department = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Alice", login_id="delete_alice", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)

        report = DailyDepartmentReport.objects.create(
            department=department,
            report_date=timezone.localdate(),
            reporter=reporter,
            total_count=1,
            followup_count=1000,
            memo="delete-me",
        )

        response = self.client.post(
            reverse("report_delete", kwargs={"dept_code": "UN", "report_id": report.id}),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("report_un"))
        self.assertFalse(DailyDepartmentReport.objects.filter(id=report.id).exists())

    def test_report_form_mode_prev_shows_previous_day_history(self):
        department = Department.objects.create(name="UN", code="UN")
        reporter = Member.objects.create(name="Alice", login_id="prev_day_alice", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)
        previous_day = timezone.localdate() - timedelta(days=1)

        DailyDepartmentReport.objects.create(
            department=department,
            report_date=previous_day,
            reporter=reporter,
            total_count=1,
            followup_count=1000,
            memo="previous-day-hit",
        )
        DailyDepartmentReport.objects.create(
            department=department,
            report_date=timezone.localdate(),
            reporter=reporter,
            total_count=1,
            followup_count=1000,
            memo="today-hit",
        )

        response = self.client.get(f"{reverse('report_un')}?mode=prev")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "previous-day-hit")
        self.assertNotContains(response, "today-hit")

    def test_wv_report_submit_edit_delete_with_split_counts(self):
        today_str = timezone.localdate().isoformat()
        department = Department.objects.create(name="WV", code="WV")
        reporter = Member.objects.create(name="WV Lead", login_id="wv_lead", password="x")
        member_2 = Member.objects.create(name="WV Bob", login_id="wv_bob", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)
        MemberDepartment.objects.create(member=member_2, department=department)

        create_response = self.client.post(
            reverse("report_wv"),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "wv create",
                "member_ids": [str(reporter.id), str(member_2.id)],
                "amounts": ["1000", "2000"],
                "counts": ["0", "0"],
                "cs_counts": ["1", "2"],
                "refugee_counts": ["2", "1"],
                "locations": ["A", "B"],
            },
        )
        self.assertEqual(create_response.status_code, 302)
        report = DailyDepartmentReport.objects.get(department=department)
        self.assertEqual(report.total_count, 6)
        self.assertEqual(report.followup_count, 3000)
        self.assertEqual(report.lines.aggregate(cs=Sum("cs_count"))["cs"], 3)
        self.assertEqual(report.lines.aggregate(ref=Sum("refugee_count"))["ref"], 3)

        edit_response = self.client.post(
            reverse("report_edit", kwargs={"report_id": report.id}),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "wv edit",
                "member_ids": [str(reporter.id)],
                "amounts": ["5000"],
                "counts": ["0"],
                "cs_counts": ["4"],
                "refugee_counts": ["1"],
                "locations": ["C"],
            },
        )
        self.assertEqual(edit_response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.memo, "wv edit")
        self.assertEqual(report.total_count, 5)
        self.assertEqual(report.followup_count, 5000)
        self.assertEqual(report.lines.count(), 1)

        delete_response = self.client.post(
            reverse("report_delete", kwargs={"dept_code": "WV", "report_id": report.id}),
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(DailyDepartmentReport.objects.filter(id=report.id).exists())

    def test_style_report_submit_edit_delete_without_location(self):
        today_str = timezone.localdate().isoformat()
        department = Department.objects.create(name="Style North", code="STYLE1")
        reporter = Member.objects.create(name="Style Lead", login_id="style_lead", password="x")
        MemberDepartment.objects.create(member=reporter, department=department)

        create_response = self.client.post(
            reverse("report_style1"),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "style create",
                "member_ids": [str(reporter.id)],
                "amounts": ["7000"],
                "counts": ["3"],
                "locations": ["IGNORED"],
            },
        )
        self.assertEqual(create_response.status_code, 302)
        report = DailyDepartmentReport.objects.get(department=department)
        self.assertEqual(report.total_count, 3)
        self.assertEqual(report.followup_count, 7000)
        self.assertEqual(report.location, "")
        self.assertEqual(report.lines.first().location, "")

        edit_response = self.client.post(
            reverse("report_edit", kwargs={"report_id": report.id}),
            data={
                "report_date": today_str,
                "reporter": reporter.id,
                "memo": "style edit",
                "member_ids": [str(reporter.id)],
                "amounts": ["8000"],
                "counts": ["4"],
                "locations": ["IGNORED2"],
            },
        )
        self.assertEqual(edit_response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.memo, "style edit")
        self.assertEqual(report.followup_count, 8000)
        self.assertEqual(report.location, "")

        delete_response = self.client.post(
            reverse("report_delete", kwargs={"dept_code": "STYLE1", "report_id": report.id}),
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(DailyDepartmentReport.objects.filter(id=report.id).exists())


class ReportTargetMonthSelectionTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["role"] = "admin"
        session.save()

    def test_report_index_month_target_uses_current_month_without_fallback(self):
        today = timezone.localdate()
        current_month = today.replace(day=1)
        old_month = (current_month - timedelta(days=1)).replace(day=1)
        un = Department.objects.create(name="UN", code="UN")
        metric = TargetMetric.objects.create(
            department=un,
            code="amount_report_old_only",
            label="Amount",
            unit="yen",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=un,
            target_month=old_month,
            metric=metric,
            status="finished",
            value=7777,
        )

        response = self.client.get(reverse("report_index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["target_month_summary"],
            f"{current_month.year}/{current_month.month}",
        )
