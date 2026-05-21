from __future__ import annotations

import base64
import json
from email.message import EmailMessage

from django.utils import timezone

from .models import MailIntegrationSetting, MailRecipientGroup, MailSendHistory


class MailSendError(Exception):
    def __init__(self, message: str, *, code: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or message


def _active_setting() -> MailIntegrationSetting | None:
    return MailIntegrationSetting.objects.filter(is_active=True).order_by("id").first()


def _build_recipient_snapshot(group: MailRecipientGroup | None) -> str:
    if group is None:
        return "未設定（モック送信）"
    recipients = []
    for member in group.members.exclude(email="").order_by("name"):
        recipients.append(f"{member.name} <{member.email}>")
    return "\n".join(recipients)


def _members_recipient_snapshot(members) -> str:
    recipients = [f"{member.name} <{member.email}>" for member in members if member.email]
    return "\n".join(recipients)


def _integration_is_ready(setting: MailIntegrationSetting | None) -> bool:
    if setting is None:
        return False
    return bool(
        setting.sender_email
        and setting.client_id
        and setting.client_secret
        and setting.refresh_token
        and setting.token_uri
    )


def _extract_error_detail(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, MailSendError):
        return exc.code, exc.detail
    response = getattr(exc, "resp", None)
    status = getattr(response, "status", "") or getattr(exc, "status_code", "")
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        content_text = content.decode("utf-8", errors="ignore")
    else:
        content_text = str(content or "")
    if content_text:
        try:
            error_payload = json.loads(content_text)
            error_block = error_payload.get("error") or {}
            code = str(error_block.get("status") or error_block.get("code") or status or exc.__class__.__name__)
            message = error_block.get("message") or content_text
            return code, str(message)
        except json.JSONDecodeError:
            pass
    reason = getattr(exc, "reason", "")
    if status or reason:
        return str(status or "network_error"), str(reason or content_text or exc)
    return exc.__class__.__name__, str(exc)


def _gmail_scopes() -> list[str]:
    return ["https://www.googleapis.com/auth/gmail.send"]


def _gmail_credentials(setting: MailIntegrationSetting):
    if not _integration_is_ready(setting):
        raise MailSendError("Gmail連携設定が不足しています。", code="missing_setting")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise MailSendError(
            "Gmail連携ライブラリが未インストールです。",
            code="missing_library",
            detail=str(exc),
        ) from exc

    credentials = Credentials.from_authorized_user_info(
        {
            "client_id": setting.client_id,
            "client_secret": setting.client_secret,
            "refresh_token": setting.refresh_token,
            "token_uri": setting.token_uri,
            "type": "authorized_user",
        },
        scopes=_gmail_scopes(),
    )
    try:
        credentials.refresh(Request())
    except Exception as exc:
        code, detail = _extract_error_detail(exc)
        raise MailSendError("アクセストークンの取得に失敗しました。", code=code, detail=detail) from exc
    if not credentials.token:
        raise MailSendError("アクセストークンが返されませんでした。", code="missing_access_token")
    return credentials


def _build_raw_message(
    *,
    sender_email: str,
    sender_name: str,
    recipients: list[str],
    subject: str,
    body: str,
) -> str:
    message = EmailMessage()
    if sender_name:
        message["From"] = f"{sender_name} <{sender_email}>"
    else:
        message["From"] = sender_email
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _send_via_gmail(
    *,
    setting: MailIntegrationSetting,
    recipients: list[str],
    subject: str,
    body: str,
) -> str:
    if not recipients:
        raise MailSendError("送信先メールアドレスがありません。", code="missing_recipient")
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise MailSendError(
            "Gmail連携ライブラリが未インストールです。",
            code="missing_library",
            detail=str(exc),
        ) from exc

    credentials = _gmail_credentials(setting)
    raw_message = _build_raw_message(
        sender_email=setting.sender_email,
        sender_name=setting.sender_name,
        recipients=recipients,
        subject=subject,
        body=body,
    )
    try:
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        response_payload = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )
    except Exception as exc:
        code, detail = _extract_error_detail(exc)
        raise MailSendError("Gmail送信に失敗しました。", code=code, detail=detail) from exc

    message_id = response_payload.get("id", "")
    if not message_id:
        raise MailSendError("Gmail送信結果に message id がありません。", code="missing_message_id")
    return str(message_id)


def send_test_mail(
    *,
    target_member=None,
    recipient_group: MailRecipientGroup | None = None,
) -> MailSendHistory:
    setting = _active_setting()
    today = timezone.localdate()
    now = timezone.now()
    if target_member is not None:
        recipients = [target_member.email] if target_member.email else []
        recipient_snapshot = _members_recipient_snapshot([target_member])
        department = target_member.default_department
        summary = target_member.name
    elif recipient_group is not None:
        members = list(recipient_group.members.exclude(email="").order_by("name"))
        recipients = [member.email for member in members]
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
            recipients=recipients,
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
