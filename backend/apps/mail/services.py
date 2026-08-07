from __future__ import annotations

from django.utils import timezone

from .gmail import (
    MailSendError,
    extract_error_detail as _extract_error_detail,
    integration_is_ready as _integration_is_ready,
    send_via_gmail as _send_via_gmail,
)
from .models import MailIntegrationSetting, MailRecipientGroup, MailSendHistory


def _active_setting() -> MailIntegrationSetting | None:
    return MailIntegrationSetting.objects.filter(is_active=True).order_by("id").first()


def active_group_members(group: MailRecipientGroup | None):
    if group is None:
        return []
    return list(group.members.filter(is_active=True).exclude(email="").order_by("name"))


def _build_recipient_snapshot(group: MailRecipientGroup | None) -> str:
    if group is None:
        return "未設定（モック送信）"
    return _members_recipient_snapshot(active_group_members(group))


def _members_recipient_snapshot(members) -> str:
    recipients = [f"{member.name} <{member.email}>" for member in members if member.email]
    return "\n".join(recipients)


def send_test_mail(
    *,
    target_member=None,
    recipient_group: MailRecipientGroup | None = None,
) -> MailSendHistory:
    setting = _active_setting()
    today = timezone.localdate()
    now = timezone.now()
    if target_member is not None:
        to_recipients = [target_member.email] if target_member.email else []
        cc_recipients = []
        recipient_snapshot = _members_recipient_snapshot([target_member])
        department = target_member.default_department
        summary = target_member.name
    elif recipient_group is not None:
        members = active_group_members(recipient_group)
        to_recipients = [setting.sender_email] if setting and setting.sender_email else []
        cc_recipients = [member.email for member in members]
        recipient_snapshot = _members_recipient_snapshot(members)
        department = recipient_group.department
        summary = recipient_group.name
    else:
        raise MailSendError("テスト送信先が指定されていません。", code="missing_target")

    subject = f"Report App Gmail連携テスト {today:%Y/%m/%d}"
    body = (
        "Gmail連携テストです。\n\n"
        f"送信元: {setting.sender_name if setting else '未設定'}\n"
        f"送信対象: {summary}\n"
        "このメールが届けば Gmail API 連携は有効です。"
    )
    history = MailSendHistory.objects.create(
        integration_setting=setting,
        department=department,
        activity_date=today,
        sender_member=None,
        transaction=None,
        recipient_group=recipient_group,
        subject_snapshot=subject,
        body_snapshot=body,
        sent_to_snapshot=recipient_snapshot,
        provider_message_id="",
        error_code="",
        error_message="",
        status=MailSendHistory.STATUS_DRAFT,
        is_test=True,
        is_resend=False,
        sent_at=None,
        last_attempt_at=now,
    )
    try:
        if not _integration_is_ready(setting):
            raise MailSendError("Gmail連携設定が未完了です。", code="missing_setting")
        provider_message_id = _send_via_gmail(
            setting=setting,
            to_recipients=to_recipients,
            cc_recipients=cc_recipients,
            subject=subject,
            body=body,
        )
    except Exception as exc:
        error_code, error_message = _extract_error_detail(exc)
        history.status = MailSendHistory.STATUS_FAILED
        history.error_code = error_code
        history.error_message = error_message
        history.provider_message_id = ""
        history.sent_at = None
        history.last_attempt_at = timezone.now()
        history.save(update_fields=["status", "error_code", "error_message", "provider_message_id", "sent_at", "last_attempt_at"])
        return history

    history.status = MailSendHistory.STATUS_SENT
    history.provider_message_id = provider_message_id
    history.error_code = ""
    history.error_message = ""
    history.sent_at = timezone.now()
    history.last_attempt_at = history.sent_at
    history.save(update_fields=["status", "provider_message_id", "error_code", "error_message", "sent_at", "last_attempt_at"])
    return history


def send_member_direct_mail(
    *,
    target_member,
    subject: str,
    body: str,
    sender_member=None,
    department=None,
    sender_name_override: str = "",
    record_history: bool = True,
) -> MailSendHistory:
    setting = _active_setting()
    now = timezone.now()
    recipient_snapshot = _members_recipient_snapshot([target_member])
    history = None
    if record_history:
        history = MailSendHistory.objects.create(
            integration_setting=setting,
            department=department or target_member.default_department,
            activity_date=timezone.localdate(),
            sender_member=sender_member,
            transaction=None,
            recipient_group=None,
            subject_snapshot=subject,
            body_snapshot=body,
            sent_to_snapshot=recipient_snapshot,
            provider_message_id="",
            error_code="",
            error_message="",
            status=MailSendHistory.STATUS_DRAFT,
            is_test=False,
            is_resend=False,
            sent_at=None,
            last_attempt_at=now,
        )
    try:
        if not target_member.email:
            raise MailSendError("メンバーのメールアドレスが未登録です。", code="missing_recipient")
        if not _integration_is_ready(setting):
            raise MailSendError("Gmail連携設定が未完了です。", code="missing_setting")
        provider_message_id = _send_via_gmail(
            setting=setting,
            to_recipients=[target_member.email],
            cc_recipients=[],
            subject=subject,
            body=body,
            sender_name_override=sender_name_override,
        )
    except Exception as exc:
        error_code, error_message = _extract_error_detail(exc)
        if history is None:
            return MailSendHistory(
                integration_setting=setting,
                department=department or target_member.default_department,
                activity_date=timezone.localdate(),
                sender_member=sender_member,
                subject_snapshot=subject,
                body_snapshot=body,
                sent_to_snapshot=recipient_snapshot,
                provider_message_id="",
                error_code=error_code,
                error_message=error_message,
                status=MailSendHistory.STATUS_FAILED,
                is_test=False,
                is_resend=False,
                sent_at=None,
                last_attempt_at=timezone.now(),
            )
        history.status = MailSendHistory.STATUS_FAILED
        history.error_code = error_code
        history.error_message = error_message
        history.provider_message_id = ""
        history.sent_at = None
        history.last_attempt_at = timezone.now()
        history.save(update_fields=["status", "error_code", "error_message", "provider_message_id", "sent_at", "last_attempt_at"])
        return history

    if history is None:
        sent_at = timezone.now()
        return MailSendHistory(
            integration_setting=setting,
            department=department or target_member.default_department,
            activity_date=timezone.localdate(),
            sender_member=sender_member,
            subject_snapshot=subject,
            body_snapshot=body,
            sent_to_snapshot=recipient_snapshot,
            provider_message_id=provider_message_id,
            error_code="",
            error_message="",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            is_resend=False,
            sent_at=sent_at,
            last_attempt_at=sent_at,
        )
    history.status = MailSendHistory.STATUS_SENT
    history.provider_message_id = provider_message_id
    history.error_code = ""
    history.error_message = ""
    history.sent_at = timezone.now()
    history.last_attempt_at = history.sent_at
    history.save(update_fields=["status", "provider_message_id", "error_code", "error_message", "sent_at", "last_attempt_at"])
    return history


def send_transaction_mail_mock(
    *,
    sender_member,
    transaction,
    recipient_group=None,
    subject,
    body,
    existing_history: MailSendHistory | None = None,
) -> MailSendHistory:
    active_setting = _active_setting()
    recipient_snapshot = _build_recipient_snapshot(recipient_group)
    history = existing_history
    if history is None:
        history = (
            transaction.mail_send_histories.filter(is_test=False)
            .order_by("-sent_at", "-created_at", "-id")
            .first()
        )
    now = timezone.now()
    timestamp = int(now.timestamp())
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
            error_code="",
            error_message="",
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
            is_resend=False,
            sent_at=now,
            last_attempt_at=now,
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
    history.error_code = ""
    history.error_message = ""
    history.status = MailSendHistory.STATUS_SENT
    history.is_test = False
    history.is_resend = True
    history.sent_at = now
    history.last_attempt_at = now
    history.save()
    transaction.mail_send_histories.exclude(id=history.id).filter(is_test=False).delete()
    return history


def send_transaction_mail(
    *,
    sender_member,
    transaction,
    recipient_group=None,
    subject,
    body,
    existing_history: MailSendHistory | None = None,
) -> MailSendHistory:
    setting = _active_setting()
    if recipient_group is None:
        raise MailSendError("送信先グループが未設定です。", code="missing_recipient_group")

    members = active_group_members(recipient_group)
    recipient_snapshot = _members_recipient_snapshot(members)
    to_recipients = [setting.sender_email] if setting and setting.sender_email else []
    cc_recipients = [member.email for member in members]
    if not _integration_is_ready(setting):
        raise MailSendError("Gmail連携設定が未完了です。", code="missing_setting")

    history = existing_history
    if history is None:
        history = (
            transaction.mail_send_histories.filter(is_test=False)
            .order_by("-last_attempt_at", "-sent_at", "-created_at", "-id")
            .first()
        )
    now = timezone.now()
    is_resend = bool(history)
    final_subject = subject
    if is_resend and final_subject and not final_subject.endswith("（再送）"):
        final_subject = f"{final_subject}（再送）"
    provider_message_id = _send_via_gmail(
        setting=setting,
        to_recipients=to_recipients,
        cc_recipients=cc_recipients,
        subject=final_subject,
        body=body,
    )
    if history is None:
        history = MailSendHistory(transaction=transaction)
    history.integration_setting = setting
    history.department = transaction.entry.department
    history.activity_date = transaction.entry.entry_date
    history.sender_member = sender_member
    history.transaction = transaction
    history.recipient_group = recipient_group
    history.subject_snapshot = final_subject
    history.body_snapshot = body
    history.sent_to_snapshot = recipient_snapshot
    history.provider_message_id = provider_message_id
    history.error_code = ""
    history.error_message = ""
    history.status = MailSendHistory.STATUS_SENT
    history.is_test = False
    history.is_resend = is_resend
    history.sent_at = now
    history.last_attempt_at = now
    history.save()
    transaction.mail_send_histories.exclude(id=history.id).filter(is_test=False).delete()
    return history


def record_transaction_mail_failure(
    *,
    sender_member,
    transaction,
    recipient_group=None,
    subject,
    body,
    error_code="",
    error_message="",
    existing_history: MailSendHistory | None = None,
) -> MailSendHistory:
    active_setting = _active_setting()
    recipient_snapshot = _build_recipient_snapshot(recipient_group)
    history = existing_history
    if history is None:
        history = (
            transaction.mail_send_histories.filter(is_test=False)
            .order_by("-last_attempt_at", "-sent_at", "-created_at", "-id")
            .first()
        )
    now = timezone.now()
    is_resend = bool(history)
    if history is None:
        history = MailSendHistory(transaction=transaction)
    history.integration_setting = active_setting
    history.department = transaction.entry.department
    history.activity_date = transaction.entry.entry_date
    history.sender_member = sender_member
    history.transaction = transaction
    history.recipient_group = recipient_group
    history.subject_snapshot = subject
    history.body_snapshot = body
    history.sent_to_snapshot = recipient_snapshot
    history.provider_message_id = ""
    history.error_code = error_code or ""
    history.error_message = error_message or ""
    history.status = MailSendHistory.STATUS_FAILED
    history.is_test = False
    history.is_resend = is_resend
    history.sent_at = None
    history.last_attempt_at = now
    history.save()
    transaction.mail_send_histories.exclude(id=history.id).filter(is_test=False).delete()
    return history
