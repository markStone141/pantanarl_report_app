import os
from dataclasses import dataclass

from django.contrib.auth import authenticate, get_user_model
from django.http import HttpRequest

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT

REPORT_USERNAME = os.getenv("REPORT_LOGIN_USERNAME", "report")
ADMIN_USERNAME = os.getenv("ADMIN_LOGIN_USERNAME", "admin")
REPORT_FIXED_PASSWORD = os.getenv("REPORT_FIXED_PASSWORD", "0823")


@dataclass(frozen=True)
class LoginResult:
    role: str | None = None
    user: object | None = None
    error_field: str | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.role is not None and self.user is not None


def get_or_create_report_user():
    user_model = get_user_model()
    report_user, created = user_model.objects.get_or_create(
        username=REPORT_USERNAME,
        defaults={"is_active": True},
    )
    if not created and not report_user.is_active:
        report_user.is_active = True
        report_user.save(update_fields=["is_active"])
    return report_user


def authenticate_login(request: HttpRequest, login_id: str, password: str) -> LoginResult:
    if login_id == ROLE_ADMIN:
        authenticated_user = authenticate(request, username=ADMIN_USERNAME, password=password)
        if authenticated_user:
            return LoginResult(role=ROLE_ADMIN, user=authenticated_user)
        return LoginResult(error_field="password", error_message="管理者パスワードが正しくありません。")

    if login_id == ROLE_REPORT:
        authenticated_user = None
        if password == REPORT_FIXED_PASSWORD:
            authenticated_user = get_or_create_report_user()
        if not authenticated_user:
            authenticated_user = authenticate(request, username=REPORT_USERNAME, password=password)
        if authenticated_user:
            return LoginResult(role=ROLE_REPORT, user=authenticated_user)
        return LoginResult(error_field="password", error_message="報告用パスワードが正しくありません。")

    return LoginResult(error_field="login_id", error_message="ログイン種別を選択してください。")
