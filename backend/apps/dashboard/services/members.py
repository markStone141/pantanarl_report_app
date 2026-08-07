from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.accounts.models import Department, Member, MemberDepartment

from apps.dashboard.forms import MemberRegistrationForm

User = get_user_model()


def member_form(*, data=None, initial=None) -> MemberRegistrationForm:
    form = MemberRegistrationForm(data=data, initial=initial)
    active_departments = Department.objects.filter(is_active=True)
    form.fields["departments"].queryset = active_departments
    form.fields["default_department"].queryset = active_departments
    form.fields["auth_login_id"].widget.attrs["placeholder"] = ""
    return form


def member_form_initial(member: Member) -> dict:
    return {
        "name": member.name,
        "un_activity_code": member.un_activity_code or "",
        "email": member.email,
        "departments": list(member.department_links.values_list("department_id", flat=True)),
        "default_department": member.default_department_id,
        "auth_login_id": member.user.username if member.user else "",
    }


def save_member_form(*, form: MemberRegistrationForm, member: Member | None = None) -> tuple[Member | None, str | None]:
    if not form.is_valid():
        return None, None

    departments = form.cleaned_data["departments"]
    default_department = form.cleaned_data["default_department"]
    member_name = form.cleaned_data["name"].strip()
    un_activity_code = form.cleaned_data.get("un_activity_code")
    member_email = (form.cleaned_data.get("email") or "").strip()
    auth_login_id = (form.cleaned_data.get("auth_login_id") or "").strip()
    auth_password = (form.cleaned_data.get("auth_password") or "").strip()
    linked_user = member.user if member else None

    if default_department and default_department not in departments:
        form.add_error("default_department", "メイン部署は所属部署から選択してください。")
        return None, None

    if un_activity_code:
        duplicate_code = Member.objects.filter(un_activity_code=un_activity_code)
        if member:
            duplicate_code = duplicate_code.exclude(id=member.id)
        if duplicate_code.exists():
            form.add_error("un_activity_code", "このUN活動コードはすでに使用されています。")
            return None, None

    if member:
        member.name = member_name
        member.un_activity_code = un_activity_code
        member.email = member_email
        member.default_department = default_department
        if auth_password and not auth_login_id and not linked_user:
            form.add_error("auth_login_id", "パスワードを設定する場合はログインIDを入力してください。")
            return None, None
        if auth_login_id:
            duplicate_user = User.objects.filter(username=auth_login_id)
            if linked_user:
                duplicate_user = duplicate_user.exclude(id=linked_user.id)
            if duplicate_user.exists():
                form.add_error("auth_login_id", "このログインIDはすでに使用されています。")
                return None, None
            if not linked_user:
                if not auth_password:
                    form.add_error("auth_password", "新規連携時はパスワードを入力してください。")
                    return None, None
                linked_user = User.objects.create_user(
                    username=auth_login_id,
                    password=auth_password,
                )
            else:
                linked_user.username = auth_login_id
                linked_user.save(update_fields=["username"])
        if linked_user and auth_password:
            linked_user.set_password(auth_password)
            linked_user.save(update_fields=["password"])
        member.user = linked_user
        member.save(update_fields=["name", "un_activity_code", "email", "user", "default_department"])
        status_message = f"{member.name} を更新しました。"
    else:
        if auth_login_id and not auth_password:
            form.add_error("auth_password", "新規作成時、ログインIDを設定する場合はパスワードが必要です。")
            return None, None
        if auth_password and not auth_login_id:
            form.add_error("auth_login_id", "パスワードを設定する場合はログインIDを入力してください。")
            return None, None
        if auth_login_id and User.objects.filter(username=auth_login_id).exists():
            form.add_error("auth_login_id", "このログインIDはすでに使用されています。")
            return None, None
        if auth_login_id:
            linked_user = User.objects.create_user(
                username=auth_login_id,
                password=auth_password,
            )
        member = Member.objects.create(
            name=member_name,
            un_activity_code=un_activity_code,
            email=member_email,
            user=linked_user,
            default_department=default_department,
        )
        status_message = f"{member.name} を登録しました。"

    MemberDepartment.objects.filter(member=member).exclude(department__in=departments).delete()
    existing_departments = set(MemberDepartment.objects.filter(member=member).values_list("department_id", flat=True))
    for dept in departments:
        if dept.id not in existing_departments:
            MemberDepartment.objects.create(member=member, department=dept)
    return member, status_message


def build_member_settings_queryset(
    *,
    query: str,
    sort: str,
    active_only: bool,
    missing_email_only: bool,
    missing_login_only: bool,
):
    members_qs = (
        Member.objects.prefetch_related("department_links__department")
        .select_related("default_department")
        .select_related("user")
    )
    if active_only:
        members_qs = members_qs.filter(is_active=True)
    if missing_email_only:
        members_qs = members_qs.filter(Q(email__isnull=True) | Q(email=""))
    if missing_login_only:
        members_qs = members_qs.filter(user__isnull=True)
    if query:
        members_qs = members_qs.filter(
            Q(name__icontains=query)
            | Q(un_activity_code__icontains=query)
            | Q(email__icontains=query)
            | Q(user__username__icontains=query)
            | Q(default_department__name__icontains=query)
            | Q(default_department__code__icontains=query)
            | Q(department_links__department__name__icontains=query)
            | Q(department_links__department__code__icontains=query)
        ).distinct()

    if sort == "oldest":
        ordering = ("id",)
    elif sort == "newest":
        ordering = ("-id",)
    elif sort == "department":
        ordering = ("default_department__code", "name", "id")
    else:
        ordering = ("name", "id")
    return members_qs.order_by(*ordering)


def build_member_row_payload(
    member: Member,
    *,
    login_input: str = "",
    email_input: str | None = None,
    un_activity_code_input: str | None = None,
    errors: list[str] | None = None,
):
    return {
        "member": member,
        "login_input": login_input,
        "email_input": member.email if email_input is None else email_input,
        "un_activity_code_input": member.un_activity_code if un_activity_code_input is None else un_activity_code_input,
        "errors": errors or [],
    }


def build_member_bulk_queryset(*, query: str, department_ids: list[int] | None = None):
    members_qs = Member.objects.select_related("user").order_by("name", "id")
    if department_ids:
        members_qs = members_qs.filter(department_links__department_id__in=department_ids).distinct()
    if query:
        members_qs = members_qs.filter(
            Q(name__icontains=query)
            | Q(email__icontains=query)
            | Q(un_activity_code__icontains=query)
            | Q(user__username__icontains=query)
        ).distinct()
    return members_qs


def extract_bulk_member_ids(post_data) -> list[int]:
    member_ids = set()
    prefixes = ("login_id_", "password_", "email_", "un_activity_code_")
    for key in post_data.keys():
        for prefix in prefixes:
            if key.startswith(prefix):
                raw_id = key[len(prefix):]
                if raw_id.isdigit():
                    member_ids.add(int(raw_id))
                break
    return sorted(member_ids)
