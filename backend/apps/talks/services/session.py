import os

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.utils.text import slugify

from apps.accounts.auth import ROLE_ADMIN, SESSION_ROLE_KEY
from apps.accounts.models import Member


TALKS_SESSION_MEMBER_ID_KEY = "talks_member_id"
TALKS_SESSION_MEMBER_NAME_KEY = "talks_member_name"
TALKS_SESSION_IS_ADMIN_KEY = "talks_is_admin"
TALKS_ADMIN_LOGIN_ID = os.getenv("TALKS_ADMIN_LOGIN_ID", "admin")
TALKS_ADMIN_PASSWORD = os.getenv("TALKS_ADMIN_PASSWORD", "pnadmin")


def get_talks_member(request: HttpRequest) -> Member | None:
    member_id = request.session.get(TALKS_SESSION_MEMBER_ID_KEY)
    if not member_id:
        return None

    member = Member.objects.active().filter(id=member_id).first()
    if not member:
        request.session.pop(TALKS_SESSION_MEMBER_ID_KEY, None)
        request.session.pop(TALKS_SESSION_MEMBER_NAME_KEY, None)
        return None
    return member


def is_talks_admin(request: HttpRequest) -> bool:
    role = request.session.get(SESSION_ROLE_KEY)
    talks_admin_flag = bool(request.session.get(TALKS_SESSION_IS_ADMIN_KEY))

    if role == ROLE_ADMIN and not talks_admin_flag:
        request.session[TALKS_SESSION_IS_ADMIN_KEY] = True
        if not request.session.get(TALKS_SESSION_MEMBER_NAME_KEY):
            request.session[TALKS_SESSION_MEMBER_NAME_KEY] = "管理者"
        talks_admin_flag = True
    elif talks_admin_flag and role != ROLE_ADMIN:
        request.session[SESSION_ROLE_KEY] = ROLE_ADMIN
        role = ROLE_ADMIN

    return role == ROLE_ADMIN or talks_admin_flag


def get_talks_display_name(request: HttpRequest, member: Member | None) -> str:
    if is_talks_admin(request):
        return request.session.get(TALKS_SESSION_MEMBER_NAME_KEY, "管理者")
    if member:
        return member.name
    return ""


def ensure_admin_user():
    User = get_user_model()
    user = User.objects.filter(username="talks_admin").first()
    if user:
        return user
    user = User.objects.create(username="talks_admin", is_staff=True)
    user.set_unusable_password()
    user.save(update_fields=["password"])
    return user


def ensure_member_user(member: Member):
    if member.user:
        return member.user

    User = get_user_model()
    base_username = slugify(member.name) or f"member-{member.id}"
    username = base_username
    suffix = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}_{suffix}"
        suffix += 1

    user = User.objects.create(username=username)
    user.set_unusable_password()
    user.save(update_fields=["password"])
    member.user = user
    member.save(update_fields=["user"])
    return user


def clear_talks_session(request: HttpRequest) -> None:
    request.session.pop(SESSION_ROLE_KEY, None)
    request.session.pop(TALKS_SESSION_IS_ADMIN_KEY, None)
    request.session.pop(TALKS_SESSION_MEMBER_ID_KEY, None)
    request.session.pop(TALKS_SESSION_MEMBER_NAME_KEY, None)
