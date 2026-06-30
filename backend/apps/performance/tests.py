import json
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment
from apps.common.test_helpers import AppTestMixin
from apps.dairymetrics.models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
    WVMetricCancellation,
)
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_member_final_actual_totals,
)
from apps.mail.models import MailSendHistory
from apps.performance.forms import PerformanceMetricAdjustmentForm
from apps.performance.services.activity_reminders import (
    activity_close_reminder_subject,
    send_pending_activity_close_reminders,
)
from apps.targets.models import MonthTargetMetricValue, Period, PeriodTargetMetricValue, TargetMetric


User = get_user_model()


class PerformanceManagementTests(AppTestMixin, TestCase):
    DEFAULT_PASSWORD = "pass1234"

    def setUp(self):
        self.user = self.create_user("perf-admin", is_staff=True)
        self.login(self.user)
        self.department = self.create_department("UN")
        self.member = self.create_member(name="Alice", department=self.department)

    def test_performance_index_renders_final_actual_rows_with_adjustment_totals(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
            result_count=2,
            support_amount=3000,
            approach_count=8,
            communication_count=4,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=entry.entry_date,
            result_count=1,
            support_amount=700,
            return_postal_count=1,
            return_postal_amount=600,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "実績管理")
        self.assertContains(response, "4件")
        self.assertContains(response, "4,300円")
        self.assertContains(response, "有効メンバー一覧")
        self.assertContains(response, "直近稼働の全体実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, "日目達成率")
        self.assertContains(response, entry.entry_date.strftime("%m/%d"))
        self.assertContains(response, "戻り・増額登録")
        self.assertContains(response, reverse("performance_adjustments"))
        self.assertContains(response, reverse("dairymetrics_entry_v2_transaction_demo"))
        self.assertContains(response, reverse("dairymetrics_metrics_v2_demo"))
        self.assertContains(response, reverse("dashboard_index"))
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, reverse("dairymetrics_metrics_report"))

    def test_performance_index_wv_overall_activity_trend_does_not_double_count_counts(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)
        entry_date = date(2026, 6, 4)
        MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=entry_date,
            result_count=2,
            support_amount=6000,
            cs_count=1,
            refugee_count=1,
            approach_count=5,
            communication_count=2,
        )
        MetricAdjustment.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=entry_date,
            support_amount=1500,
            result_count=1,
            cs_count=1,
            refugee_count=0,
        )

        response = self.client.get(reverse("performance_index"), {"dashboard_department": wv_department.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_snapshot"]["overall_activity_trend"]["counts"], [3])
        self.assertEqual(response.context["dashboard_snapshot"]["overall_activity_trend"]["cs_counts"], [2])
        self.assertEqual(response.context["dashboard_snapshot"]["overall_activity_trend"]["refugee_counts"], [1])

    def test_wv_cancellation_subtracts_from_final_actuals_without_changing_field_entry(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Cancel Member", department=wv_department)
        entry = MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=date(2026, 6, 7),
            result_count=2,
            support_amount=6500,
            cs_count=1,
            refugee_count=1,
        )
        WVMetricCancellation.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=entry.entry_date,
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=1,
            location_name="横浜駅前",
        )

        entry.refresh_from_db()
        totals = collect_member_final_actual_totals(
            wv_member,
            wv_department,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(entry.result_count, 2)
        self.assertEqual(entry.support_amount, 6500)
        self.assertEqual(totals["result_count"], 1)
        self.assertEqual(totals["support_amount"], 2000)
        self.assertEqual(totals["cs_count"], 0)
        self.assertEqual(totals["refugee_count"], 1)

    def test_wv_refugee_cancellation_subtracts_only_refugee_side(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Refugee Cancel", department=wv_department)
        MemberDailyMetricEntry.objects.create(
            member=wv_member,
            department=wv_department,
            entry_date=date(2026, 6, 8),
            result_count=2,
            support_amount=7500,
            cs_count=1,
            refugee_count=1,
        )
        WVMetricCancellation.objects.create(
            member=wv_member,
            department=wv_department,
            target_date=date(2026, 6, 8),
            wv_result_type=MemberMetricTransaction.WV_RESULT_REFUGEE,
            wv_refugee_amount=3000,
        )

        totals = collect_department_final_actual_totals(
            wv_department,
            date(2026, 6, 1),
            date(2026, 6, 30),
        )

        self.assertEqual(totals["result_count"], 1)
        self.assertEqual(totals["support_amount"], MemberMetricTransaction.WV_CS_UNIT_AMOUNT)
        self.assertEqual(totals["cs_count"], 1)
        self.assertEqual(totals["refugee_count"], 0)

    def test_performance_past_entry_create_renders_department_specific_transaction_inputs(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)

        un_response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": self.department.id, "member": self.member.id, "entry_date": "2026-06-01"},
        )
        self.assertEqual(un_response.status_code, 200)
        self.assertContains(un_response, "決済金額")
        self.assertNotContains(un_response, "CS口数")

        wv_response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": wv_department.id, "member": wv_member.id, "entry_date": "2026-06-01"},
        )
        self.assertEqual(wv_response.status_code, 200)
        self.assertContains(wv_response, "CS口数")
        self.assertContains(wv_response, "難民支援金額")

    def test_performance_past_entry_create_saves_un_entry_and_transactions(self):
        response = self.client.post(
            reverse("performance_past_entry_create"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "entry_date": "2026-06-01",
                "location_name": "渋谷駅前",
                "approach_count": "8",
                "communication_count": "3",
                "transactions_payload": json.dumps(
                    [
                        {
                            "support_amount": 3000,
                            "wv_result_type": "",
                            "wv_cs_count": 0,
                            "wv_refugee_amount": 0,
                            "age_band": MemberMetricTransaction.AGE_BAND_TWENTIES,
                            "is_student": False,
                            "gender": MemberMetricTransaction.GENDER_FEMALE,
                            "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                            "comment": "過去UN",
                        }
                    ]
                ),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_past_entry_create')}?department={self.department.id}&member={self.member.id}&saved=1",
        )
        entry = MemberDailyMetricEntry.objects.get(member=self.member, department=self.department, entry_date=date(2026, 6, 1))
        self.assertTrue(entry.activity_closed)
        self.assertEqual(entry.location_name, "渋谷駅前")
        self.assertEqual(entry.approach_count, 8)
        self.assertEqual(entry.communication_count, 3)
        self.assertEqual(entry.result_count, 1)
        self.assertEqual(entry.support_amount, 3000)
        self.assertEqual(entry.transactions.count(), 1)
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=date(2026, 6, 1))
        self.assertEqual(summary.approach_count, 8)
        self.assertEqual(summary.communication_count, 3)
        self.assertEqual(summary.result_count, 1)
        self.assertEqual(summary.support_amount, 3000)

    def test_performance_past_entry_create_saves_wv_entry_and_transactions(self):
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="WV Member", department=wv_department)

        response = self.client.post(
            reverse("performance_past_entry_create"),
            {
                "department": wv_department.id,
                "member": wv_member.id,
                "entry_date": "2026-06-01",
                "location_name": "新宿駅前",
                "approach_count": "10",
                "communication_count": "4",
                "transactions_payload": json.dumps(
                    [
                        {
                            "support_amount": 6500,
                            "wv_result_type": MemberMetricTransaction.WV_RESULT_BOTH,
                            "wv_cs_count": 1,
                            "wv_refugee_amount": 2000,
                            "age_band": MemberMetricTransaction.AGE_BAND_THIRTIES,
                            "is_student": False,
                            "gender": MemberMetricTransaction.GENDER_MALE,
                            "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                            "comment": "過去WV",
                        }
                    ]
                ),
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_past_entry_create')}?department={wv_department.id}&member={wv_member.id}&saved=1",
        )
        entry = MemberDailyMetricEntry.objects.get(member=wv_member, department=wv_department, entry_date=date(2026, 6, 1))
        self.assertEqual(entry.result_count, 2)
        self.assertEqual(entry.cs_count, 1)
        self.assertEqual(entry.refugee_count, 1)
        self.assertEqual(entry.support_amount, 6500)

    def test_performance_past_entry_create_blocks_duplicate_entry_dates(self):
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 1),
            result_count=1,
            support_amount=1000,
        )

        response = self.client.post(
            reverse("performance_past_entry_create"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "entry_date": "2026-06-01",
                "location_name": "渋谷駅前",
                "approach_count": "8",
                "communication_count": "3",
                "transactions_payload": "[]",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "その日の実績はすでに登録されています。")

    def test_performance_past_entry_create_shows_edit_and_delete_for_existing_future_entry(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 15),
            result_count=1,
            support_amount=1000,
        )

        response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": self.department.id, "member": self.member.id, "entry_date": "2026-06-15"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_entry_edit", args=[entry.id]))
        self.assertContains(response, reverse("performance_entry_delete", args=[entry.id]))

    def test_performance_member_dashboard_nav_includes_report_app(self):
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-report-nav", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])
        self.client.force_login(member_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("report_index"))
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, reverse("dairymetrics_metrics_report"))

    def test_performance_member_dashboard_redirects_to_performance_login(self):
        self.client.logout()

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('performance_login')}?next={reverse('performance_member_dashboard')}",
        )

    def test_performance_index_defaults_dashboard_department_to_un(self):
        other_department = Department.objects.create(code="WV", name="WV", is_active=True)
        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].code, "UN")
        self.assertContains(response, "月目標達成率")

    def test_performance_index_uses_active_period_even_if_finished_period_param_exists(self):
        today = timezone.localdate()
        finished_period = Period.objects.create(
            month=today.replace(day=1),
            name="終了済み路程",
            status="finished",
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=7),
        )
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="現在Active路程",
            status="active",
            start_date=today,
            end_date=today + timedelta(days=6),
        )

        response = self.client.get(
            reverse("performance_index"),
            {"dashboard_period": str(finished_period.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_period"].id, active_period.id)
        self.assertContains(response, "現在Active路程")
        self.assertNotContains(response, "終了済み路程進捗")

    def test_performance_history_ignores_finished_period_param_unless_period_scope(self):
        today = timezone.localdate()
        finished_period = Period.objects.create(
            month=today.replace(day=1),
            name="終了済み路程",
            status="finished",
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=7),
        )
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="現在Active路程",
            status="active",
            start_date=today,
            end_date=today + timedelta(days=6),
        )

        response = self.client.get(
            reverse("performance_history"),
            {
                "dashboard_scope": "month",
                "dashboard_department": str(self.department.id),
                "dashboard_period": str(finished_period.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_period"].id, active_period.id)

    def test_performance_index_can_switch_dashboard_department(self):
        other_department = Department.objects.create(code="WV", name="WV", is_active=True)

        response = self.client.get(reverse("performance_index"), {"dashboard_department": other_department.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].id, other_department.id)
        self.assertContains(
            response,
            f'<option value="{other_department.id}" selected>WV</option>',
            html=True,
        )

    def test_performance_history_defaults_dashboard_department_to_member_default_for_report_role(self):
        self.client.logout()
        member_user, member_profile = self.create_member_user(
            username="perf-history-member",
            name="History Member",
            department=self.department,
            default_department=self.department,
        )
        other_department = self.create_department("WV")
        MemberDepartment.objects.create(member=member_profile, department=other_department)
        self.client.force_login(member_user)

        response = self.client.get(reverse("performance_history"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_department"].id, self.department.id)

    @patch("apps.performance.views.send_member_direct_mail")
    def test_performance_index_can_send_activity_reminder(self, mocked_send_member_direct_mail):
        reminder_member = self.create_member(
            name="Reminder Target",
            department=self.department,
            email="reminder@example.com",
        )
        entry = MemberDailyMetricEntry.objects.create(
            member=reminder_member,
            department=self.department,
            entry_date=timezone.localdate(),
            activity_closed=False,
            support_amount=0,
            result_count=0,
        )
        mocked_send_member_direct_mail.return_value = MailSendHistory(status=MailSendHistory.STATUS_SENT)

        response = self.client.post(
            reverse("performance_send_activity_reminder", args=[entry.id]),
            {"next": reverse("performance_index")},
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_index')}?status=Reminder+Target%E3%81%95%E3%82%93%E3%81%B8%E3%83%AA%E3%83%9E%E3%82%A4%E3%83%B3%E3%83%89%E3%82%92%E9%80%81%E4%BF%A1%E3%81%97%E3%81%BE%E3%81%97%E3%81%9F%E3%80%82",
            fetch_redirect_response=False,
        )
        mocked_send_member_direct_mail.assert_called_once()
        self.assertEqual(mocked_send_member_direct_mail.call_args.kwargs["target_member"], reminder_member)
        self.assertEqual(mocked_send_member_direct_mail.call_args.kwargs["sender_name_override"], "おつかれさまです")
        self.assertIn("活動お疲れ様でした。活動終了が確認できていませんのでお手数ですが入力をよろしくお願いします。", mocked_send_member_direct_mail.call_args.kwargs["body"])

    @patch("apps.performance.services.activity_reminders.send_member_direct_mail")
    def test_auto_activity_reminder_sends_to_open_members_with_email(self, mocked_send_member_direct_mail):
        today = timezone.localdate()
        reminder_member = self.create_member(
            name="Auto Reminder",
            email="auto-reminder@example.com",
            department=self.department,
        )
        closed_member = self.create_member(
            name="Closed Reminder",
            email="closed-reminder@example.com",
            department=self.department,
        )
        no_email_member = self.create_member(name="No Email Reminder", email="", department=self.department)
        inactive_member = self.create_member(
            name="Inactive Reminder",
            email="inactive-reminder@example.com",
            department=self.department,
            is_active=False,
        )
        open_entry = MemberDailyMetricEntry.objects.create(
            member=reminder_member,
            department=self.department,
            entry_date=today,
            activity_closed=False,
        )
        MemberDailyMetricEntry.objects.create(
            member=closed_member,
            department=self.department,
            entry_date=today,
            activity_closed=True,
        )
        MemberDailyMetricEntry.objects.create(
            member=no_email_member,
            department=self.department,
            entry_date=today,
            activity_closed=False,
        )
        MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=today,
            activity_closed=False,
        )
        mocked_send_member_direct_mail.return_value = MailSendHistory(status=MailSendHistory.STATUS_SENT)
        now = timezone.make_aware(datetime.combine(today, time(19, 5)))

        result = send_pending_activity_close_reminders(now=now)

        self.assertEqual(result.checked, 1)
        self.assertEqual(result.sent, 1)
        self.assertEqual(result.failed, 0)
        mocked_send_member_direct_mail.assert_called_once()
        self.assertEqual(mocked_send_member_direct_mail.call_args.kwargs["target_member"], reminder_member)
        self.assertEqual(mocked_send_member_direct_mail.call_args.kwargs["department"], self.department)
        self.assertEqual(mocked_send_member_direct_mail.call_args.kwargs["subject"], activity_close_reminder_subject(open_entry))

    @patch("apps.performance.services.activity_reminders.send_member_direct_mail")
    def test_auto_activity_reminder_skips_before_configured_time(self, mocked_send_member_direct_mail):
        today = timezone.localdate()
        reminder_member = self.create_member(
            name="Before Time",
            email="before-time@example.com",
            department=self.department,
        )
        MemberDailyMetricEntry.objects.create(
            member=reminder_member,
            department=self.department,
            entry_date=today,
            activity_closed=False,
        )
        now = timezone.make_aware(datetime.combine(today, time(18, 59)))

        result = send_pending_activity_close_reminders(now=now)

        self.assertEqual(result.reason, "before_reminder_time")
        mocked_send_member_direct_mail.assert_not_called()

    @patch("apps.performance.services.activity_reminders.send_member_direct_mail")
    def test_auto_activity_reminder_skips_already_sent_member(self, mocked_send_member_direct_mail):
        today = timezone.localdate()
        reminder_member = self.create_member(
            name="Already Sent",
            email="already-sent@example.com",
            department=self.department,
        )
        entry = MemberDailyMetricEntry.objects.create(
            member=reminder_member,
            department=self.department,
            entry_date=today,
            activity_closed=False,
        )
        MailSendHistory.objects.create(
            department=self.department,
            activity_date=today,
            sender_member=None,
            subject_snapshot=activity_close_reminder_subject(entry),
            body_snapshot="sent",
            sent_to_snapshot=f"{reminder_member.name} <{reminder_member.email}>",
            provider_message_id="gmail-reminder",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            is_resend=False,
            sent_at=timezone.now(),
            last_attempt_at=timezone.now(),
        )
        now = timezone.make_aware(datetime.combine(today, time(19, 5)))

        result = send_pending_activity_close_reminders(now=now)

        self.assertEqual(result.checked, 1)
        self.assertEqual(result.skipped, 1)
        mocked_send_member_direct_mail.assert_not_called()

    def test_performance_past_entry_create_get_with_department_shows_member_options(self):
        response = self.client.get(
            reverse("performance_past_entry_create"),
            {"department": self.department.id, "entry_date": "2026-06-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<option value="{self.member.id}">{self.member.name}</option>', html=True)
        self.assertContains(response, "dashboard/mobile_drawer.js")

    def test_performance_past_entry_member_options_returns_department_members(self):
        self.member.un_activity_code = "12345"
        self.member.save(update_fields=["un_activity_code"])
        other_department = self.create_department("WV")
        other_member = self.create_member(name="Other Member", department=other_department)
        un_matched_member = self.create_member(name="UN Other", department=self.department)
        un_matched_member.un_activity_code = "98765"
        un_matched_member.save(update_fields=["un_activity_code"])

        response = self.client.get(
            reverse("performance_past_entry_member_options"),
            {"department": self.department.id, "un_code": "123"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["options"],
            [{"id": self.member.id, "name": self.member.name, "un_activity_code": "12345"}],
        )
        self.assertNotIn(
            {"id": other_member.id, "name": other_member.name, "un_activity_code": other_member.un_activity_code},
            payload["options"],
        )
        self.assertNotIn(
            {"id": un_matched_member.id, "name": un_matched_member.name, "un_activity_code": "98765"},
            payload["options"],
        )

    def test_performance_admin_entries_page_shows_summary_and_entry_actions(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 3),
            approach_count=7,
            communication_count=4,
            result_count=2,
            support_amount=3500,
            location_name="渋谷駅前",
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=7,
            communication_count=4,
            result_count=2,
            support_amount=3500,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.get(reverse("performance_admin_entries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全体エントリー管理")
        self.assertContains(response, "UN / 2026/06/03")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "渋谷駅前")
        self.assertContains(response, reverse("performance_entry_edit", args=[entry.id]))
        self.assertContains(response, reverse("performance_entry_delete", args=[entry.id]))

    def test_performance_closeout_notes_lists_and_filters_member_memos(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            location_name="新宿駅前",
            memo="話は進んだが予算の確認が必要だった。次は比較資料を準備する。",
            activity_closed=True,
        )
        other_member = self.create_member(name="Bob", department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=today,
            memo="別のケース",
            activity_closed=True,
        )

        response = self.client.get(
            reverse("performance_closeout_notes"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "q": "比較資料",
                "date_from": today.strftime("%Y-%m-%d"),
                "date_to": today.strftime("%Y-%m-%d"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "あと一歩ケース")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "新宿駅前")
        self.assertContains(response, "次は比較資料を準備する。")
        self.assertNotContains(response, "別のケース")

    def test_performance_admin_entries_includes_inactive_member_filter_option(self):
        inactive_member = self.create_member(name="Inactive Entry", department=self.department)
        inactive_member.is_active = False
        inactive_member.save(update_fields=["is_active"])

        response = self.client.get(reverse("performance_admin_entries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<option value="{inactive_member.id}">{inactive_member.name}</option>', html=True)

    def test_performance_admin_entries_can_delete_orphan_summary(self):
        summary = DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=date(2026, 6, 4),
            approach_count=0,
            communication_count=0,
            result_count=0,
            support_amount=0,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.post(
            reverse("performance_summary_delete", args=[summary.id]),
            {"next": reverse("performance_admin_entries")},
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_admin_entries')}?deleted=summary",
            fetch_redirect_response=False,
        )
        self.assertFalse(DepartmentDailyMetricSummary.objects.filter(pk=summary.id).exists())

    def test_performance_admin_entries_does_not_delete_summary_with_entries(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 5),
            result_count=1,
            support_amount=1000,
        )
        summary = DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=0,
            communication_count=0,
            result_count=1,
            support_amount=1000,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.post(
            reverse("performance_summary_delete", args=[summary.id]),
            {"next": reverse("performance_admin_entries")},
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_admin_entries')}?status=summary_not_empty",
            fetch_redirect_response=False,
        )
        self.assertTrue(DepartmentDailyMetricSummary.objects.filter(pk=summary.id).exists())

    def test_performance_index_auto_closes_stale_open_entries(self):
        stale_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate() - timedelta(days=1),
            result_count=1,
            support_amount=1000,
            activity_closed=False,
            activity_closed_at=None,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        stale_entry.refresh_from_db()
        self.assertTrue(stale_entry.activity_closed)
        self.assertIsNotNone(stale_entry.activity_closed_at)

    def test_performance_login_redirects_member_to_member_dashboard(self):
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-login", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])

        response = self.client.post(
            reverse("performance_login"),
            {"login_id": "perf-member-login", "password": "pass1234"},
        )

        self.assertRedirects(response, reverse("performance_member_dashboard"))

    def test_performance_login_redirects_admin_to_admin_dashboard(self):
        self.client.logout()

        response = self.client.post(
            reverse("performance_login"),
            {"login_id": "perf-admin", "password": "pass1234"},
        )

        self.assertRedirects(response, reverse("performance_index"))

    def test_performance_logout_redirects_to_performance_login(self):
        response = self.client.get(reverse("performance_logout"))

        self.assertRedirects(response, reverse("performance_login"))

    def test_performance_history_uses_selected_month_and_period_for_progress_cards(self):
        today = timezone.localdate()
        selected_month = date(today.year, 4, 1)
        selected_period = Period.objects.create(
            month=selected_month,
            name="4月第2次路程",
            status="closed",
            start_date=selected_month,
            end_date=selected_month + timedelta(days=6),
        )
        amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=self.department,
            target_month=selected_month,
            metric=amount_metric,
            value=12000,
        )
        PeriodTargetMetricValue.objects.create(
            period=selected_period,
            department=self.department,
            metric=amount_metric,
            value=28000,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_month + timedelta(days=1),
            result_count=1,
            support_amount=4500,
        )

        response = self.client.get(
            reverse("performance_history"),
            {
                "dashboard_scope": "period",
                "dashboard_department": str(self.department.id),
                "dashboard_month": selected_month.strftime("%Y-%m"),
                "dashboard_period": str(selected_period.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4月第2次路程")
        self.assertContains(response, f"{selected_period.start_date:%Y/%m/%d} - {selected_period.end_date:%Y/%m/%d}")
        self.assertContains(response, "4,500円")
        self.assertContains(response, "16.1%")
        self.assertContains(response, "過去の実績を見る")

    def test_performance_index_and_history_show_today_transaction_and_mail_details(self):
        today = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            approach_count=4,
            communication_count=2,
            location_name="渋谷駅前",
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
            comment="当日詳細",
        )
        MailSendHistory.objects.create(
            department=self.department,
            activity_date=today,
            sender_member=self.member,
            transaction=transaction,
            subject_snapshot="【UN】当日送信",
            body_snapshot="本文です",
            sent_to_snapshot="group@example.com",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            sent_at=timezone.now(),
            last_attempt_at=timezone.now(),
        )

        index_response = self.client.get(reverse("performance_index"))
        history_response = self.client.get(reverse("performance_history"))

        self.assertEqual(index_response.status_code, 200)
        self.assertContains(index_response, "本日の決済詳細")
        self.assertContains(index_response, "本日の送信メール詳細")
        self.assertContains(index_response, "【UN】当日送信")
        self.assertContains(index_response, "本文です")
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, "本日の決済詳細")
        self.assertContains(history_response, "本日の送信メール詳細")
        self.assertContains(history_response, "【UN】当日送信")

    def test_performance_today_transaction_detail_shows_admin_cancel_action(self):
        today = timezone.localdate()
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_transaction_edit", args=[transaction.id]))
        self.assertContains(response, reverse("performance_transaction_delete", args=[transaction.id]))
        self.assertContains(response, "決済を取り消す")

    def test_admin_can_cancel_transaction_and_revert_totals(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 6, 20),
            result_count=0,
            support_amount=0,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷駅前",
        )
        mail_history = MailSendHistory.objects.create(
            department=self.department,
            activity_date=entry.entry_date,
            sender_member=self.member,
            transaction=transaction,
            subject_snapshot="送信済み",
            body_snapshot="本文",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            sent_at=timezone.now(),
        )

        response = self.client.post(
            reverse("performance_transaction_delete", args=[transaction.id]),
            {"next": reverse("performance_index")},
        )

        self.assertRedirects(response, f"{reverse('performance_index')}?deleted=transaction")
        self.assertFalse(MemberMetricTransaction.objects.filter(pk=transaction.pk).exists())
        entry.refresh_from_db()
        self.assertEqual(entry.result_count, 0)
        self.assertEqual(entry.support_amount, 0)
        mail_history.refresh_from_db()
        self.assertIsNone(mail_history.transaction_id)

    def test_performance_entry_edit_updates_daily_entry_and_department_summary(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
            result_count=1,
            support_amount=2000,
            approach_count=5,
            communication_count=2,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=5,
            communication_count=2,
            result_count=1,
            support_amount=2000,
            created_by=self.member,
            updated_by=self.member,
        )

        response = self.client.post(
            reverse("performance_entry_edit", args=[entry.id]),
            {
                "department": self.department.id,
                "entry_date": "2026-05-15",
                "approach_count": 9,
                "communication_count": 6,
                "result_count": 3,
                "support_amount": 4500,
                "daily_target_count": 0,
                "daily_target_amount": 0,
                "location_name": "",
                "memo": "",
            },
        )

        self.assertRedirects(response, reverse("performance_index") + "?updated=entry")
        entry.refresh_from_db()
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry.entry_date)
        self.assertEqual(entry.approach_count, 9)
        self.assertEqual(entry.communication_count, 6)
        self.assertEqual(entry.result_count, 3)
        self.assertEqual(entry.support_amount, 4500)
        self.assertEqual(summary.approach_count, 9)
        self.assertEqual(summary.communication_count, 6)
        self.assertEqual(summary.result_count, 3)
        self.assertEqual(summary.support_amount, 4500)

    def test_performance_entry_edit_locks_amount_when_transactions_exist(self):
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=date(2026, 5, 15),
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
        )

        response = self.client.get(reverse("performance_entry_edit", args=[entry.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "自動計算されます。")
        self.assertContains(response, "disabled")

    def test_performance_adjustment_create_sets_creator(self):
        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-14",
                "source_type": MetricAdjustment.SOURCE_QR,
                "location_name": "渋谷駅前",
                "amount_choice": "1500",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 14))
        self.assertEqual(adjustment.created_by, self.user)
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_QR)
        self.assertEqual(adjustment.return_qr_count, 1)
        self.assertEqual(adjustment.return_qr_amount, 1500)
        self.assertEqual(adjustment.location_name, "渋谷駅前")
        self.assertEqual(adjustment.support_amount, 0)

    def test_performance_adjustment_create_increase_counts_as_one(self):
        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-15",
                "source_type": MetricAdjustment.SOURCE_INCREASE,
                "location_name": "池袋駅前",
                "amount_choice": "direct",
                "amount": "6200",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 15))
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_INCREASE)
        self.assertEqual(adjustment.result_count, 1)
        self.assertEqual(adjustment.support_amount, 6200)
        self.assertEqual(adjustment.location_name, "池袋駅前")

    def test_performance_adjustment_member_options_include_un_activity_code(self):
        self.member.un_activity_code = "12345"
        self.member.save(update_fields=["un_activity_code"])

        response = self.client.get(reverse("performance_adjustments"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UNコード")
        self.assertContains(response, "performance-selected-member-preview")
        options = response.context["member_options"][str(self.department.id)]
        self.assertEqual(options[0]["id"], self.member.id)
        self.assertEqual(options[0]["name"], self.member.name)
        self.assertEqual(options[0]["un_activity_code"], "12345")

    def test_performance_adjustment_create_wv_cs_sets_fixed_amount_and_count(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])

        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-16",
                "source_type": MetricAdjustment.SOURCE_CS,
                "location_name": "横浜駅前",
                "amount_choice": "500",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 16))
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_CS)
        self.assertEqual(adjustment.result_count, 1)
        self.assertEqual(adjustment.cs_count, 1)
        self.assertEqual(adjustment.refugee_count, 0)
        self.assertEqual(adjustment.support_amount, MemberMetricTransaction.WV_CS_UNIT_AMOUNT)
        self.assertEqual(adjustment.location_name, "横浜駅前")

    def test_performance_adjustment_create_wv_cs_plus_refugee_sets_split_counts(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])

        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-17",
                "source_type": MetricAdjustment.SOURCE_CS_PLUS_REFUGEE,
                "location_name": "川崎駅前",
                "amount_choice": "1500",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        adjustment = MetricAdjustment.objects.get(member=self.member, department=self.department, target_date=date(2026, 5, 17))
        self.assertEqual(adjustment.source_type, MetricAdjustment.SOURCE_CS_PLUS_REFUGEE)
        self.assertEqual(adjustment.result_count, 2)
        self.assertEqual(adjustment.cs_count, 1)
        self.assertEqual(adjustment.refugee_count, 1)
        self.assertEqual(adjustment.support_amount, MemberMetricTransaction.WV_CS_UNIT_AMOUNT + 1500)
        self.assertEqual(adjustment.location_name, "川崎駅前")

    def test_performance_adjustment_create_wv_cancel_saves_cancellation_record(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])

        response = self.client.post(
            reverse("performance_adjustments"),
            {
                "department": self.department.id,
                "member": self.member.id,
                "target_date": "2026-05-18",
                "source_type": PerformanceMetricAdjustmentForm.SOURCE_CANCEL,
                "cancel_result_type": MemberMetricTransaction.WV_RESULT_BOTH,
                "cancel_cs_count": "1",
                "location_name": "横浜駅前",
                "amount_choice": "2000",
                "amount": "",
            },
        )

        self.assertRedirects(response, reverse("performance_adjustments") + "?saved=1")
        self.assertFalse(MetricAdjustment.objects.filter(member=self.member, target_date=date(2026, 5, 18)).exists())
        cancellation = WVMetricCancellation.objects.get(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 18),
        )
        self.assertEqual(cancellation.created_by, self.user)
        self.assertEqual(cancellation.wv_result_type, MemberMetricTransaction.WV_RESULT_BOTH)
        self.assertEqual(cancellation.cs_count, 1)
        self.assertEqual(cancellation.refugee_count, 1)
        self.assertEqual(cancellation.support_amount, MemberMetricTransaction.WV_CS_UNIT_AMOUNT + 2000)
        self.assertEqual(cancellation.location_name, "横浜駅前")

    def test_performance_adjustments_list_shows_wv_cancellation_and_can_delete(self):
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])
        cancellation = WVMetricCancellation.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 19),
            wv_result_type=MemberMetricTransaction.WV_RESULT_CS,
            wv_cs_count=1,
            location_name="川崎駅前",
            created_by=self.user,
        )

        response = self.client.get(reverse("performance_adjustments"), {"department": self.department.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "キャンセル")
        self.assertContains(response, "川崎駅前")
        self.assertContains(response, "CS 1 / 難民 0")

        delete_response = self.client.post(reverse("performance_cancellation_delete", args=[cancellation.id]))

        self.assertRedirects(delete_response, reverse("performance_adjustments"))
        self.assertFalse(WVMetricCancellation.objects.filter(pk=cancellation.pk).exists())

    def test_performance_adjustments_ajax_filters_by_department(self):
        other_department = self.create_department("WV")
        other_member = self.create_member(name="Bob", department=other_department)
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 10),
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
            location_name="渋谷駅前",
        )
        MetricAdjustment.objects.create(
            member=other_member,
            department=other_department,
            target_date=date(2026, 5, 11),
            source_type=MetricAdjustment.SOURCE_CS,
            support_amount=MemberMetricTransaction.WV_CS_UNIT_AMOUNT,
            result_count=1,
            cs_count=1,
            location_name="横浜駅前",
        )

        response = self.client.get(
            reverse("performance_adjustments"),
            {"department": other_department.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("list_html", payload)
        self.assertIn("Bob", payload["list_html"])
        self.assertIn("WV", payload["list_html"])
        self.assertNotIn("Alice", payload["list_html"])
        self.assertNotIn("UN", payload["list_html"])

    def test_performance_adjustments_ajax_searches_source_type_display_label(self):
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 10),
            source_type=MetricAdjustment.SOURCE_INCREASE,
            result_count=1,
            support_amount=3000,
            location_name="東京A現場",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 11),
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=1500,
            location_name="東京B現場",
        )

        response = self.client.get(
            reverse("performance_adjustments"),
            {"q": "増額"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        list_html = response.json()["list_html"]
        self.assertIn("東京A現場", list_html)
        self.assertIn("増額", list_html)
        self.assertNotIn("東京B現場", list_html)

    def test_performance_adjustments_ajax_returns_load_more_button(self):
        for index in range(21):
            MetricAdjustment.objects.create(
                member=self.member,
                department=self.department,
                target_date=date(2026, 5, 1) + timedelta(days=index),
                source_type=MetricAdjustment.SOURCE_INCREASE,
                result_count=1,
                support_amount=1000 + index,
                location_name=f"現場{index:02d}",
            )

        response = self.client.get(
            reverse("performance_adjustments"),
            {"page": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("list_html", payload)
        self.assertIn("現場00", payload["list_html"] or "")
        self.assertNotIn("performance-adjustments-load-more-btn", payload["list_html"])

    def test_performance_adjustments_default_list_shows_all_departments(self):
        other_department = self.create_department("WV")
        other_member = self.create_member(name="Bob", department=other_department)
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=date(2026, 5, 10),
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
            location_name="渋谷駅前",
        )
        MetricAdjustment.objects.create(
            member=other_member,
            department=other_department,
            target_date=date(2026, 5, 11),
            source_type=MetricAdjustment.SOURCE_CS,
            support_amount=MemberMetricTransaction.WV_CS_UNIT_AMOUNT,
            result_count=1,
            cs_count=1,
            location_name="横浜駅前",
        )

        response = self.client.get(reverse("performance_adjustments"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")
        self.assertContains(response, "UN")
        self.assertContains(response, "WV")

    def test_performance_index_shows_activity_lists_and_progress_with_adjustments(self):
        today = timezone.localdate()
        other_member = Member.objects.create(name="Bob", default_department=self.department)
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=5),
        )
        amount_metric = TargetMetric.objects.create(
            department=self.department,
            code="amount",
            label="金額",
            unit="円",
            display_order=1,
            is_active=True,
        )
        MonthTargetMetricValue.objects.create(
            department=self.department,
            target_month=today.replace(day=1),
            metric=amount_metric,
            value=10000,
        )
        PeriodTargetMetricValue.objects.create(
            period=active_period,
            department=self.department,
            metric=amount_metric,
            value=30000,
        )
        active_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            daily_target_amount=8000,
            location_name="渋谷駅前",
            activity_closed=False,
        )
        finished_entry = MemberDailyMetricEntry.objects.create(
            member=other_member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=2000,
            daily_target_amount=8000,
            location_name="新宿駅前",
            activity_closed=True,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=today,
            daily_target_count=3,
            daily_target_amount=8000,
            created_by=self.member,
            updated_by=self.member,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            support_amount=500,
        )
        MetricAdjustment.objects.create(
            member=other_member,
            department=self.department,
            target_date=today - timedelta(days=1),
            support_amount=1500,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "現在活動中メンバー")
        self.assertContains(response, "活動終了メンバー")
        self.assertContains(response, "今日の合計件数")
        self.assertContains(response, "2件")
        self.assertContains(response, "今日の合計金額")
        self.assertContains(response, "5,000円")
        self.assertContains(response, "8,000円")
        self.assertContains(response, "62.5%")
        self.assertContains(response, active_entry.member.name)
        self.assertContains(response, finished_entry.member.name)
        self.assertContains(response, "3,000円 / 8,000円")
        self.assertContains(response, "2,000円 / 8,000円")
        self.assertContains(response, "目標達成率")
        self.assertContains(response, "70.0%")
        self.assertContains(response, "7,000円")
        self.assertContains(response, "現場: 渋谷駅前")
        self.assertContains(response, "現場: 新宿駅前")
        self.assertContains(response, "補正 2,000円")
        self.assertContains(response, "通常実績")
        self.assertContains(response, "補正実績")
        self.assertContains(response, "残り")
        self.assertContains(response, 'data-chart-values="5000,2000,3000"', html=False)
        self.assertContains(response, "5月第2次路程")
        self.assertContains(response, f"{active_period.start_date:%Y/%m/%d} - {active_period.end_date:%Y/%m/%d}")

    def test_performance_index_shows_active_member_cards_with_detail_link(self):
        today = timezone.localdate()
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        active_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            activity_closed=False,
        )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=2,
            support_amount=2500,
            activity_closed=True,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            support_amount=500,
        )
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "有効メンバー一覧")
        self.assertContains(response, self.member.name)
        self.assertContains(response, "今月累計")
        self.assertContains(response, "路程累計")
        self.assertContains(response, "直近の実績")
        self.assertContains(response, reverse("performance_member_insight", args=[self.member.id, self.department.id]))

    def test_performance_index_shows_enabled_member_card_without_today_entry(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=2),
            result_count=2,
            support_amount=2800,
            activity_closed=True,
        )

    def test_performance_member_dashboard_syncs_finished_period_when_dates_overlap_today(self):
        today = timezone.localdate()
        period = Period.objects.create(
            month=today.replace(day=1),
            name=f"{today.year}年度{today.month}月 第1次路程",
            status="finished",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=period,
            target_amount=9999,
        )
        self.client.logout()
        member_user = User.objects.create_user(username="perf-member-finished-period", password="pass1234", is_staff=False)
        self.member.user = member_user
        self.member.save(update_fields=["user"])
        self.client.force_login(member_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "9,999円")
        period.refresh_from_db()
        self.assertEqual(period.status, "active")

    def test_performance_member_detail_uses_active_period_even_if_finished_period_param_exists(self):
        today = timezone.localdate()
        finished_period = Period.objects.create(
            month=today.replace(day=1),
            name="終了済み個人路程",
            status="finished",
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=7),
        )
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="現在Active個人路程",
            status="active",
            start_date=today,
            end_date=today + timedelta(days=6),
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=finished_period,
            target_amount=9999,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(
            reverse("performance_member_detail", args=[self.member.id, self.department.id]),
            {"dashboard_period": str(finished_period.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period_label"], active_period.name)
        self.assertContains(response, "現在Active個人路程")
        self.assertNotContains(response, "終了済み個人路程進捗")

    def test_performance_index_shows_wv_total_count_with_breakdown_subtext(self):
        today = timezone.localdate()
        self.department.code = "WV"
        self.department.name = "WV"
        self.department.save(update_fields=["code", "name"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            support_amount=6500,
            result_count=2,
            cs_count=1,
            refugee_count=1,
            activity_closed=True,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=entry.entry_date,
            source_type=MetricAdjustment.SOURCE_CS,
            support_amount=MemberMetricTransaction.WV_CS_UNIT_AMOUNT,
            result_count=1,
            cs_count=1,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3件")
        self.assertContains(response, "(CS 2件 / 難民 1件)")

    def test_performance_index_orders_enabled_member_cards_by_recent_entry_desc(self):
        today = timezone.localdate()
        newer_member = Member.objects.create(name="Newer", default_department=self.department)
        older_member = Member.objects.create(name="Older", default_department=self.department)
        MemberDepartment.objects.create(member=newer_member, department=self.department)
        MemberDepartment.objects.create(member=older_member, department=self.department)
        MemberDailyMetricEntry.objects.create(
            member=older_member,
            department=self.department,
            entry_date=today - timedelta(days=3),
            support_amount=1000,
        )
        MemberDailyMetricEntry.objects.create(
            member=newer_member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            support_amount=2000,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertLess(content.index("Newer"), content.index("Older"))

    def test_performance_index_marks_member_when_last_three_entries_are_zero_count(self):
        today = timezone.localdate()
        for offset in range(3):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=0,
                support_amount=0,
                activity_closed=True,
            )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3稼働連続0件")

    def test_performance_index_does_not_mark_zero_streak_until_third_entry_is_closed(self):
        today = timezone.localdate()
        for offset in (1, 2):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=0,
                support_amount=0,
                activity_closed=True,
            )
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=0,
            support_amount=0,
            activity_closed=False,
        )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "3稼働連続0件")

    def test_performance_index_streak_uses_adjustment_counts(self):
        today = timezone.localdate()
        for offset in range(3):
            entry = MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=0,
                support_amount=0,
                activity_closed=True,
            )
            if offset == 0:
                MetricAdjustment.objects.create(
                    member=self.member,
                    department=self.department,
                    target_date=entry.entry_date,
                    source_type=MetricAdjustment.SOURCE_INCREASE,
                    result_count=1,
                    support_amount=500,
                )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "3稼働連続0件")

    def test_performance_index_marks_member_when_last_three_entries_have_results(self):
        today = timezone.localdate()
        for offset, count in enumerate((2, 1, 3)):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=count,
                support_amount=1000 * count,
                activity_closed=True,
            )

        response = self.client.get(reverse("performance_index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3稼働連続1件以上")

    def test_performance_member_detail_shows_realtime_dashboard(self):
        today = timezone.localdate()
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        entry_today = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            approach_count=8,
            communication_count=4,
        )
        entry_old = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=2,
            support_amount=2500,
            approach_count=6,
            communication_count=3,
        )
        MemberMetricTransaction.objects.create(
            entry=entry_today,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=900,
        )
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績ダッシュボード")
        self.assertContains(response, "直近稼働の実績推移")
        self.assertContains(response, "performance-activity-trend-chart")
        self.assertContains(response, "-10")
        self.assertContains(response, "+10")
        self.assertContains(response, "日目達成率")
        self.assertContains(response, "AP/CM")
        self.assertContains(response, entry_today.entry_date.strftime("%m/%d"))
        self.assertContains(response, "全体の月目標")
        self.assertContains(response, "全体の路程目標")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "個人の路程目標")
        self.assertContains(response, "Aliceさんの割合")
        self.assertContains(response, "9,400円 / 9,400円")
        self.assertContains(response, "月目標")
        self.assertContains(response, "修正")
        self.assertContains(response, "直近30日の実績")
        self.assertContains(response, "直近30日の補正実績")
        self.assertContains(response, f'{reverse("dairymetrics_metrics_v2_demo")}?department={self.department.code}')
        self.assertEqual(response.context["activity_trend"]["amounts"], [2500, 6900])
        self.assertEqual(response.context["activity_trend"]["counts"], [2, 3])
        self.assertContains(response, "補正実績件数")
        self.assertContains(response, "1件")
        self.assertContains(response, "補正実績金額")
        self.assertContains(response, "900円")

    def test_performance_member_detail_limits_recent_dashboard_rows_to_five(self):
        today = timezone.localdate()
        created_dates = []
        for offset in range(7):
            entry_date = today - timedelta(days=offset)
            created_dates.append(entry_date)
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=entry_date,
                result_count=offset + 1,
                support_amount=1000 * (offset + 1),
                activity_closed=True,
                location_name="渋谷駅前" if offset == 0 else "",
            )

        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["recent_entry_rows"]), 5)
        self.assertContains(response, created_dates[0].strftime("%Y/%m/%d"))
        self.assertContains(response, created_dates[4].strftime("%Y/%m/%d"))
        self.assertContains(response, "渋谷駅前")
        self.assertNotContains(response, created_dates[5].strftime("%Y/%m/%d"))
        self.assertContains(response, "さらに5件表示")
        self.assertContains(response, 'data-performance-recent-date-search', html=False)

    def test_performance_member_detail_recent_detail_ajax_filters_by_date(self):
        today = timezone.localdate()
        selected_day = today - timedelta(days=1)
        other_day = today - timedelta(days=3)
        selected_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=3000,
            activity_closed=True,
            location_name="現場A",
        )
        other_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=other_day,
            result_count=2,
            support_amount=4500,
            activity_closed=True,
            location_name="現場B",
        )
        MemberMetricTransaction.objects.create(
            entry=selected_entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="選択日決済",
        )
        MemberMetricTransaction.objects.create(
            entry=other_entry,
            support_amount=4500,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="池袋",
            comment="別日決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=selected_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1200,
            location_name="現場A",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=other_day,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=700,
            location_name="現場B",
        )

        response = self.client.get(
            reverse("performance_member_detail_recent_detail", args=[self.member.id, self.department.id]),
            {"date": selected_day.isoformat(), "limit": 5},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "選択日決済")
        self.assertContains(response, "現場A")
        self.assertContains(response, 'data-label="現場">現場A', html=False)
        self.assertNotContains(response, "別日決済")
        self.assertNotContains(response, "現場B")
        self.assertNotContains(response, "さらに5件表示")

    def test_performance_member_dashboard_recent_detail_uses_logged_in_member(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-recent", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        selected_day = timezone.localdate() - timedelta(days=2)
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=2500,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=2500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="新宿",
            comment="本人 recent detail",
        )
        self.client.force_login(report_user)

        response = self.client.get(
            reverse("performance_member_dashboard_recent_detail"),
            {"date": selected_day.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本人 recent detail")
        self.assertContains(response, reverse("performance_member_dashboard"))

    def test_performance_member_history_shows_scoped_entries_and_adjustments(self):
        today = timezone.localdate()
        active_period = Period.objects.create(
            month=today.replace(day=1),
            name="5月第2次路程",
            status="active",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        entry_today = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
            approach_count=8,
            communication_count=4,
            location_name="渋谷駅前",
        )
        MemberMetricTransaction.objects.create(
            entry=entry_today,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=900,
        )
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )
        MemberPeriodMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            period=active_period,
            target_amount=20000,
        )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の過去の実績")
        self.assertContains(response, "集計条件")
        self.assertContains(response, "全体の月目標")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "日次実績")
        self.assertContains(response, "補正実績")
        self.assertContains(response, entry_today.entry_date.strftime("%Y/%m/%d"))
        self.assertContains(response, "渋谷駅前")
        self.assertContains(response, "郵送")
        self.assertContains(response, ">2件<", html=False)
        self.assertContains(response, "<th>現場</th>", html=False)
        self.assertContains(response, ">-<", html=False)
        self.assertContains(response, "900円")
        self.assertContains(response, "初回決済")
        self.assertContains(response, "<th>操作</th>", html=False)
        self.assertContains(response, 'aria-label="過去の実績を修正"', html=False)
        self.assertContains(response, 'aria-label="日次実績を削除"', html=False)
        self.assertNotContains(response, "<th>状態</th>", html=False)
        self.assertNotContains(response, "<th>メモ</th>", html=False)

    def test_performance_member_history_limits_initial_rows_to_five(self):
        today = timezone.localdate()
        for offset in range(7):
            MemberDailyMetricEntry.objects.create(
                member=self.member,
                department=self.department,
                entry_date=today - timedelta(days=offset),
                result_count=1,
                support_amount=1000 * (offset + 1),
                activity_closed=True,
            )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["entry_rows"]), 5)
        self.assertContains(response, "さらに5件表示")
        self.assertContains(response, 'data-performance-history-date-links', html=False)

    def test_performance_history_includes_inactive_member_with_scope_records(self):
        today = timezone.localdate()
        inactive_user, inactive_member = self.create_member_user(
            username="inactive_history_member",
            password="pass123",
            name="Inactive History",
            department=self.department,
        )
        inactive_member.is_active = False
        inactive_member.save(update_fields=["is_active"])
        MemberDailyMetricEntry.objects.create(
            member=inactive_member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=2000,
            activity_closed=True,
        )

        response = self.client.get(
            reverse("performance_history"),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m"), "department": self.department.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inactive History")

    def test_performance_member_history_range_uses_date_input_filter(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today - timedelta(days=1),
            result_count=1,
            support_amount=1500,
            activity_closed=True,
        )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {
                "dashboard_scope": "range",
                "dashboard_start": (today - timedelta(days=10)).isoformat(),
                "dashboard_end": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-performance-history-date-search', html=False)
        self.assertNotContains(response, 'data-performance-history-date-links', html=False)

    def test_performance_member_history_shows_qr_adjustment_amount_and_count(self):
        today = timezone.localdate()
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=today,
            result_count=1,
            support_amount=3000,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=today,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
            location_name="現場A",
        )

        response = self.client.get(
            reverse("performance_member_history_detail", args=[self.member.id, self.department.id]),
            {"dashboard_scope": "month", "dashboard_month": today.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QR")
        self.assertContains(response, "1件")
        self.assertContains(response, "1500円")
        self.assertContains(response, "補正実績")
        self.assertContains(response, "現場A")

    def test_performance_member_dashboard_trend_includes_adjustment_only_dates(self):
        today = timezone.localdate()
        entry_day = today - timedelta(days=1)
        adjustment_only_day = today - timedelta(days=3)
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=entry_day,
            result_count=1,
            support_amount=3000,
            approach_count=4,
            communication_count=2,
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=adjustment_only_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1500,
        )

        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["activity_trend"]["labels"],
            [adjustment_only_day.strftime("%m/%d"), entry_day.strftime("%m/%d")],
        )
        self.assertEqual(
            response.context["activity_trend"]["dates"],
            [adjustment_only_day.isoformat(), entry_day.isoformat()],
        )
        self.assertEqual(response.context["activity_trend"]["amounts"], [1500, 3000])
        self.assertEqual(response.context["activity_trend"]["counts"], [1, 1])

    def test_performance_member_history_day_detail_returns_selected_day_rows(self):
        today = timezone.localdate()
        selected_day = today - timedelta(days=1)
        other_day = today - timedelta(days=2)
        selected_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=3000,
            approach_count=5,
            communication_count=2,
            activity_closed=True,
        )
        other_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=other_day,
            result_count=2,
            support_amount=6000,
            approach_count=8,
            communication_count=4,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=selected_entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="選択日の決済",
        )
        MemberMetricTransaction.objects.create(
            entry=other_entry,
            support_amount=6000,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="池袋",
            comment="別日の決済",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=selected_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1200,
            location_name="現場A",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=other_day,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=700,
            location_name="現場B",
        )

        response = self.client.get(
            reverse("performance_member_history_detail_day_detail", args=[self.member.id, self.department.id]),
            {"date": selected_day.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{selected_day:%Y/%m/%d} の日次実績")
        self.assertContains(response, "選択日の決済")
        self.assertContains(response, "現場A")
        self.assertContains(response, "1200円")
        self.assertNotContains(response, "別日の決済")
        self.assertNotContains(response, "現場B")

    def test_performance_member_history_day_detail_uses_logged_in_member(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-day-detail", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        selected_day = timezone.localdate() - timedelta(days=1)
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=2500,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=2500,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="新宿",
            comment="本人日次",
        )
        self.client.force_login(report_user)

        response = self.client.get(
            reverse("performance_member_history_day_detail"),
            {"date": selected_day.isoformat()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本人日次")
        self.assertContains(response, reverse("performance_member_history"))

    def test_performance_member_history_list_ajax_filters_by_date(self):
        today = timezone.localdate()
        selected_day = today - timedelta(days=1)
        other_day = today - timedelta(days=3)
        selected_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=selected_day,
            result_count=1,
            support_amount=3000,
            activity_closed=True,
        )
        other_entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=other_day,
            result_count=2,
            support_amount=4500,
            activity_closed=True,
        )
        MemberMetricTransaction.objects.create(
            entry=selected_entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="履歴選択日",
        )
        MemberMetricTransaction.objects.create(
            entry=other_entry,
            support_amount=4500,
            age_band=MemberMetricTransaction.AGE_BAND_THIRTIES,
            gender=MemberMetricTransaction.GENDER_MALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="池袋",
            comment="履歴別日",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=selected_day,
            source_type=MetricAdjustment.SOURCE_QR,
            return_qr_count=1,
            return_qr_amount=1200,
            location_name="現場A",
        )
        MetricAdjustment.objects.create(
            member=self.member,
            department=self.department,
            target_date=other_day,
            source_type=MetricAdjustment.SOURCE_POSTAL,
            return_postal_count=1,
            return_postal_amount=700,
            location_name="現場B",
        )

        response = self.client.get(
            reverse("performance_member_history_detail_list", args=[self.member.id, self.department.id]),
            {
                "dashboard_scope": "month",
                "dashboard_month": today.strftime("%Y-%m"),
                "date": selected_day.isoformat(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "履歴選択日")
        self.assertContains(response, "現場A")
        self.assertNotContains(response, "履歴別日")
        self.assertNotContains(response, "現場B")

    def test_performance_member_detail_shows_target_forms_when_edit_requested(self):
        today = timezone.localdate()
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
            target_amount=10000,
        )

        response = self.client.get(
            reverse("performance_member_detail", args=[self.member.id, self.department.id]),
            {"month": today.strftime("%Y-%m"), "edit_month_target": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "月目標を保存")

    def test_performance_member_dashboard_uses_logged_in_member_profile(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        MemberMonthMetricTarget.objects.create(
            member=self.member,
            department=self.department,
            target_month=timezone.localdate().replace(day=1),
            target_amount=9000,
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の実績ダッシュボード")
        self.assertContains(response, "個人の月目標")
        self.assertContains(response, "直近30日の実績")
        self.assertContains(response, "直近30日の補正実績")
        self.assertContains(response, reverse("performance_member_history"))
        self.assertContains(response, "実績管理ダッシュボード")
        self.assertContains(response, "全体実績")
        self.assertContains(response, reverse("performance_index"))
        self.assertContains(response, "決済入力")
        self.assertContains(response, "過去の実績を見る")
        self.assertContains(response, "分析する")
        self.assertContains(response, "振り返りレポート")
        self.assertContains(response, reverse("dairymetrics_metrics_report"))
        self.assertNotContains(response, "総合管理者ページ")

    def test_performance_member_can_open_overall_dashboard_and_history(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-overall", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        self.client.force_login(report_user)

        dashboard_response = self.client.get(reverse("performance_index"))
        history_response = self.client.get(reverse("performance_history"))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, "本日の活動状況")
        self.assertContains(dashboard_response, "全体実績")
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, "集計条件")
        self.assertContains(history_response, "全体実績")

    def test_performance_member_insight_is_readonly_for_member_viewer(self):
        self.client.logout()
        viewer_user = User.objects.create_user(username="perf-viewer", password="pass1234", is_staff=False)
        self.member.user = viewer_user
        self.member.save(update_fields=["user"])
        teammate = Member.objects.create(name="Teammate", default_department=self.department)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        MemberMonthMetricTarget.objects.create(
            member=teammate,
            department=self.department,
            target_month=timezone.localdate().replace(day=1),
            target_amount=8000,
        )
        self.client.force_login(viewer_user)

        response = self.client.get(reverse("performance_member_insight", args=[teammate.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{teammate.name} の実績ダッシュボード")
        self.assertContains(
            response,
            f'{reverse("dairymetrics_metrics_v2_demo")}?department={self.department.code}&member={teammate.id}',
        )
        self.assertContains(response, reverse("performance_member_insight", args=[teammate.id, self.department.id]))
        self.assertContains(response, reverse("performance_member_history_insight", args=[teammate.id, self.department.id]))
        self.assertNotContains(response, "このメンバーの 分析する")
        self.assertNotContains(response, "月目標を保存")
        self.assertNotContains(response, "路程目標を保存")

    def test_admin_member_detail_menu_links_to_that_members_history(self):
        response = self.client.get(reverse("performance_member_detail", args=[self.member.id, self.department.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_index"))
        self.assertContains(response, reverse("performance_member_detail", args=[self.member.id, self.department.id]))
        self.assertContains(response, reverse("performance_member_history_detail", args=[self.member.id, self.department.id]))

    def test_performance_member_history_uses_logged_in_member_profile(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-history", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=1,
            support_amount=3000,
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.member.name} の過去の実績")
        self.assertContains(response, "集計条件")
        self.assertContains(response, "実績管理ダッシュボード")
        self.assertContains(response, "決済入力")
        self.assertContains(response, "分析する")

    def test_performance_member_history_shows_transaction_edit_link(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-history-link", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=0,
            support_amount=0,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        self.client.force_login(report_user)

        response = self.client.get(reverse("performance_member_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_transaction_edit", args=[transaction.id]))

    def test_performance_member_can_edit_own_transaction_from_history_flow(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-tx-edit", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate() - timedelta(days=1),
            result_count=0,
            support_amount=0,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="初回決済",
        )
        self.client.force_login(report_user)

        response = self.client.post(
            f"{reverse('performance_transaction_edit', args=[transaction.id])}?next={reverse('performance_member_history')}",
            {
                "support_amount": 4200,
                "wv_result_type": "",
                "wv_cs_count": 0,
                "wv_refugee_amount": 0,
                "location": "渋谷",
                "age_band": MemberMetricTransaction.AGE_BAND_TWENTIES,
                "is_student": "",
                "gender": MemberMetricTransaction.GENDER_FEMALE,
                "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
                "comment": "金額修正",
                "next": reverse("performance_member_history"),
            },
        )

        self.assertRedirects(response, f"{reverse('performance_member_history')}?updated=transaction")
        transaction.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(transaction.support_amount, 4200)
        self.assertEqual(entry.support_amount, 4200)

    def test_performance_member_can_edit_own_past_entry_from_history_flow(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-edit", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=0,
            support_amount=0,
            approach_count=0,
            communication_count=0,
        )
        self.client.force_login(report_user)

        history_response = self.client.get(reverse("performance_member_history"))
        self.assertContains(history_response, reverse("performance_entry_edit", args=[entry.id]))

        response = self.client.post(
            f"{reverse('performance_entry_edit', args=[entry.id])}?next={reverse('performance_member_history')}",
            {
                "member": self.member.id,
                "department": self.department.id,
                "entry_date": entry.entry_date.strftime("%Y-%m-%d"),
                "approach_count": 12,
                "communication_count": 4,
                "result_count": 0,
                "support_amount": 0,
                "daily_target_count": 1,
                "daily_target_amount": 3000,
                "activity_closed": "on",
                "location_name": "",
                "memo": "",
                "next": reverse("performance_member_history"),
            },
        )

        self.assertRedirects(response, f"{reverse('performance_member_history')}?updated=entry")
        entry.refresh_from_db()
        self.assertEqual(entry.approach_count, 12)
        self.assertEqual(entry.communication_count, 4)

    def test_performance_member_can_delete_own_past_entry_from_history_flow(self):
        self.client.logout()
        report_user = User.objects.create_user(username="perf-member-delete", password="pass1234", is_staff=False)
        self.member.user = report_user
        self.member.save(update_fields=["user"])
        entry = MemberDailyMetricEntry.objects.create(
            member=self.member,
            department=self.department,
            entry_date=timezone.localdate() - timedelta(days=1),
            result_count=1,
            support_amount=3000,
            approach_count=5,
            communication_count=2,
        )
        DepartmentDailyMetricSummary.objects.create(
            department=self.department,
            entry_date=entry.entry_date,
            approach_count=5,
            communication_count=2,
            result_count=1,
            support_amount=3000,
            created_by=self.member,
            updated_by=self.member,
        )
        self.client.force_login(report_user)

        response = self.client.post(
            f"{reverse('performance_entry_delete', args=[entry.id])}?next={reverse('performance_member_history')}",
            {
                "next": reverse("performance_member_history"),
            },
        )

        self.assertRedirects(response, f"{reverse('performance_member_history')}?deleted=entry")
        self.assertFalse(MemberDailyMetricEntry.objects.filter(pk=entry.id).exists())
        summary = DepartmentDailyMetricSummary.objects.get(department=self.department, entry_date=entry.entry_date)
        self.assertEqual(summary.result_count, 0)
        self.assertEqual(summary.support_amount, 0)

    def test_admin_member_history_insight_shows_edit_and_delete_actions(self):
        teammate = Member.objects.create(name="Teammate", default_department=self.department)
        MemberDepartment.objects.create(member=teammate, department=self.department)
        entry = MemberDailyMetricEntry.objects.create(
            member=teammate,
            department=self.department,
            entry_date=timezone.localdate(),
            result_count=1,
            support_amount=3000,
        )
        transaction = MemberMetricTransaction.objects.create(
            entry=entry,
            support_amount=3000,
            age_band=MemberMetricTransaction.AGE_BAND_TWENTIES,
            gender=MemberMetricTransaction.GENDER_FEMALE,
            nationality_type=MemberMetricTransaction.NATIONALITY_DOMESTIC,
            location="渋谷",
            comment="管理者確認",
        )

        response = self.client.get(
            reverse("performance_member_history_insight", args=[teammate.id, self.department.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("performance_entry_edit", args=[entry.id]))
        self.assertContains(response, reverse("performance_entry_delete", args=[entry.id]))
        self.assertContains(response, reverse("performance_transaction_edit", args=[transaction.id]))

    def test_performance_member_detail_can_save_month_target(self):
        today = timezone.localdate()

        response = self.client.post(
            f"{reverse('performance_member_detail', args=[self.member.id, self.department.id])}?month={today:%Y-%m}",
            {
                "action": "save_month_target",
                "department": self.department.id,
                "target_count": 3,
                "target_amount": 12000,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_member_detail', args=[self.member.id, self.department.id])}?month={today:%Y-%m}&saved=target",
        )
        target = MemberMonthMetricTarget.objects.get(
            member=self.member,
            department=self.department,
            target_month=today.replace(day=1),
        )
        self.assertEqual(target.target_count, 3)
        self.assertEqual(target.target_amount, 12000)

    def test_performance_member_detail_can_save_wv_month_target_with_split_counts(self):
        today = timezone.localdate()
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="Wv Member", department=wv_department)

        response = self.client.post(
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}",
            {
                "action": "save_month_target",
                "department": wv_department.id,
                "target_cs_count": 4,
                "target_refugee_count": 3,
                "target_amount": 28000,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}&saved=target",
        )
        target = MemberMonthMetricTarget.objects.get(
            member=wv_member,
            department=wv_department,
            target_month=today.replace(day=1),
        )
        self.assertEqual(target.target_cs_count, 4)
        self.assertEqual(target.target_refugee_count, 3)
        self.assertEqual(target.target_count, 7)
        self.assertEqual(target.target_amount, 28000)

    def test_performance_member_detail_can_save_wv_period_target_with_split_counts(self):
        today = timezone.localdate()
        wv_department = self.create_department("WV")
        wv_member = self.create_member(name="Wv Period Member", department=wv_department)
        current_period = Period.objects.create(
            name="2026年5月 第4次路程",
            month=today.replace(day=1),
            status="active",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=2),
        )

        response = self.client.post(
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}",
            {
                "action": "save_period_target",
                "department": wv_department.id,
                "target_cs_count": 5,
                "target_refugee_count": 2,
                "target_amount": 32000,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('performance_member_detail', args=[wv_member.id, wv_department.id])}?month={today:%Y-%m}&saved=target",
        )
        target = MemberPeriodMetricTarget.objects.get(
            member=wv_member,
            department=wv_department,
            period=current_period,
        )
        self.assertEqual(target.target_cs_count, 5)
        self.assertEqual(target.target_refugee_count, 2)
        self.assertEqual(target.target_count, 7)
        self.assertEqual(target.target_amount, 32000)
