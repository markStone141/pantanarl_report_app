from __future__ import annotations

import base64
import json
from email.message import EmailMessage

from .models import MailIntegrationSetting


class MailSendError(Exception):
    def __init__(self, message: str, *, code: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or message


def integration_is_ready(setting: MailIntegrationSetting | None) -> bool:
    if setting is None:
        return False
    return bool(
        setting.sender_email
        and setting.client_id
        and setting.client_secret
        and setting.refresh_token
        and setting.token_uri
    )


def extract_error_detail(exc: Exception) -> tuple[str, str]:
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
    if not integration_is_ready(setting):
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
        code, detail = extract_error_detail(exc)
        raise MailSendError("アクセストークンの取得に失敗しました。", code=code, detail=detail) from exc
    if not credentials.token:
        raise MailSendError("アクセストークンが返されませんでした。", code="missing_access_token")
    return credentials


def build_raw_message(
    *,
    sender_email: str,
    sender_name: str,
    to_recipients: list[str],
    cc_recipients: list[str] | None = None,
    subject: str,
    body: str,
) -> str:
    message = EmailMessage()
    if sender_name:
        message["From"] = f"{sender_name} <{sender_email}>"
    else:
        message["From"] = sender_email
    message["To"] = ", ".join(to_recipients)
    if cc_recipients:
        message["Cc"] = ", ".join(cc_recipients)
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def send_via_gmail(
    *,
    setting: MailIntegrationSetting,
    to_recipients: list[str],
    cc_recipients: list[str] | None = None,
    subject: str,
    body: str,
    sender_name_override: str = "",
) -> str:
    if not to_recipients and not cc_recipients:
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
    raw_message = build_raw_message(
        sender_email=setting.sender_email,
        sender_name=sender_name_override or setting.sender_name,
        to_recipients=to_recipients,
        cc_recipients=cc_recipients,
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
        code, detail = extract_error_detail(exc)
        raise MailSendError("Gmail送信に失敗しました。", code=code, detail=detail) from exc

    message_id = response_payload.get("id", "")
    if not message_id:
        raise MailSendError("Gmail送信結果に message id がありません。", code="missing_message_id")
    return str(message_id)
