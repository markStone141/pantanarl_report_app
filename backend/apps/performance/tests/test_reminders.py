from datetime import datetime, time
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.dairymetrics.models import MemberDailyMetricEntry
from apps.mail.models import MailSendHistory
from apps.performance.services.activity_reminders import activity_close_reminder_subject, send_pending_activity_close_reminders
from .base import PerformanceTestBase


class RemindersTests(PerformanceTestBase):
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
        self.assertFalse(mocked_send_member_direct_mail.call_args.kwargs["record_history"])
        open_entry.refresh_from_db()
        self.assertIsNotNone(open_entry.activity_reminder_sent_at)


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
    def test_auto_activity_reminder_skips_entry_with_reminder_marker(self, mocked_send_member_direct_mail):
        today = timezone.localdate()
        reminder_member = self.create_member(
            name="Already Marked",
            email="already-marked@example.com",
            department=self.department,
        )
        MemberDailyMetricEntry.objects.create(
            member=reminder_member,
            department=self.department,
            entry_date=today,
            activity_closed=False,
            activity_reminder_sent_at=timezone.now(),
        )
        now = timezone.make_aware(datetime.combine(today, time(19, 5)))

        result = send_pending_activity_close_reminders(now=now)

        self.assertEqual(result.checked, 1)
        self.assertEqual(result.skipped, 1)
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
