from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from django.db.models import Q
from django.utils import timezone

from apps.dairymetrics.models import MemberDailyMetricEntry
from apps.mail.models import MailSendHistory
from apps.mail.services import send_member_direct_mail


AUTO_REMINDER_SUBJECT_PREFIX = "【自動リマインド】"
DEFAULT_AUTO_REMINDER_TIME = time(19, 0)


@dataclass
class ActivityReminderResult:
    checked: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    dry_run: bool = False
    reason: str = ""


def activity_close_reminder_subject(entry: MemberDailyMetricEntry) -> str:
    return f"{AUTO_REMINDER_SUBJECT_PREFIX}{entry.entry_date:%Y/%m/%d} の活動終了をお願いします"


def activity_close_reminder_body(entry: MemberDailyMetricEntry) -> str:
    return (
        f"{entry.member.name}さん\n\n"
        "活動お疲れ様でした。\n"
        "本日の活動終了がまだ確認できていません。\n"
        "お手数ですが、活動終了ボタンから最終実績の保存をお願いします。"
    )


def activity_close_reminder_already_sent(entry: MemberDailyMetricEntry) -> bool:
    return MailSendHistory.objects.filter(
        activity_date=entry.entry_date,
        transaction__isnull=True,
        is_test=False,
        status=MailSendHistory.STATUS_SENT,
        subject_snapshot=activity_close_reminder_subject(entry),
        sent_to_snapshot__contains=entry.member.email,
    ).exists()


def pending_activity_close_reminder_entries(*, entry_date):
    return (
        MemberDailyMetricEntry.objects.filter(
            entry_date=entry_date,
            activity_closed=False,
            member__is_active=True,
        )
        .exclude(Q(member__email="") | Q(member__email__isnull=True))
        .select_related("member", "department")
        .order_by("department__code", "member__name", "id")
    )


def send_activity_close_reminder(entry: MemberDailyMetricEntry) -> MailSendHistory:
    return send_member_direct_mail(
        target_member=entry.member,
        sender_member=None,
        department=entry.department,
        sender_name_override="活動終了リマインド",
        subject=activity_close_reminder_subject(entry),
        body=activity_close_reminder_body(entry),
    )


def send_pending_activity_close_reminders(*, now=None, target_date=None, force=False, dry_run=False) -> ActivityReminderResult:
    local_now = timezone.localtime(now or timezone.now())
    if not force and local_now.time() < DEFAULT_AUTO_REMINDER_TIME:
        return ActivityReminderResult(reason="before_reminder_time", dry_run=dry_run)

    entry_date = target_date or local_now.date()
    entries = list(pending_activity_close_reminder_entries(entry_date=entry_date))
    result = ActivityReminderResult(checked=len(entries), dry_run=dry_run)
    for entry in entries:
        if activity_close_reminder_already_sent(entry):
            result.skipped += 1
            continue
        if dry_run:
            result.skipped += 1
            continue
        history = send_activity_close_reminder(entry)
        if history.status == MailSendHistory.STATUS_SENT:
            result.sent += 1
        else:
            result.failed += 1
    return result
