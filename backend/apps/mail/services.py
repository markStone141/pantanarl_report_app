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


def send_transaction_mail_mock(
    *,
    sender_member,
    transaction,
    recipient_group=None,
    subject,
    body,
    existing_history: MailSendHistory | None = None,
) -> MailSendHistory:
    active_setting = MailIntegrationSetting.objects.filter(is_active=True).order_by("id").first()
    recipient_snapshot = _build_recipient_snapshot(recipient_group)
    history = existing_history
    if history is None:
        history = (
            transaction.mail_send_histories.filter(status=MailSendHistory.STATUS_SENT, is_test=False)
            .order_by("-sent_at", "-created_at", "-id")
            .first()
        )
    timestamp = int(timezone.now().timestamp())
    if history is None:
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
            provider_message_id=f"mock-{transaction.id}-{timestamp}",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            is_resend=False,
            sent_at=timezone.now(),
        )

    resend_subject = subject
    if not resend_subject.endswith("（再送）"):
        resend_subject = f"{resend_subject}（再送）"
    history.integration_setting = active_setting
    history.department = transaction.entry.department
    history.activity_date = transaction.entry.entry_date
    history.sender_member = sender_member
    history.transaction = transaction
    history.recipient_group = recipient_group
    history.subject_snapshot = resend_subject
    history.body_snapshot = body
    history.sent_to_snapshot = recipient_snapshot
    history.provider_message_id = f"mock-{transaction.id}-{timestamp}"
    history.status = MailSendHistory.STATUS_SENT
    history.is_test = False
    history.is_resend = True
    history.sent_at = timezone.now()
    history.save()
    transaction.mail_send_histories.exclude(id=history.id).filter(status=MailSendHistory.STATUS_SENT, is_test=False).delete()
    return history
