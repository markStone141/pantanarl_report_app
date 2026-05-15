from __future__ import annotations

from django.utils import timezone

from .models import MailIntegrationSetting, MailRecipientGroup, MailSendHistory


def _build_recipient_snapshot(group: MailRecipientGroup | None) -> str:
    if group is None:
        return "未設定（モック送信）"
    recipients = []
    for member in group.members.exclude(email="").order_by("name"):
        recipients.append(f"{member.name} <{member.email}>")
    return "\n".join(recipients)


def send_transaction_mail_mock(*, sender_member, transaction, recipient_group=None, subject, body) -> MailSendHistory:
    active_setting = MailIntegrationSetting.objects.filter(is_active=True).order_by("id").first()
    recipient_snapshot = _build_recipient_snapshot(recipient_group)
    is_resend = transaction.mail_send_histories.filter(status=MailSendHistory.STATUS_SENT, is_test=False).exists()
    return MailSendHistory.objects.create(
        integration_setting=active_setting,
        department=transaction.entry.department,
        activity_date=transaction.entry.entry_date,
        sender_member=sender_member,
        transaction=transaction,
        recipient_group=recipient_group,
        subject_snapshot=subject,
        body_snapshot=body,
        sent_to_snapshot=recipient_snapshot,
        provider_message_id=f"mock-{transaction.id}-{int(timezone.now().timestamp())}",
        status=MailSendHistory.STATUS_SENT,
        is_test=False,
        is_resend=is_resend,
        sent_at=timezone.now(),
    )
