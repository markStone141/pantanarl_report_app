from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.auth import ROLE_ADMIN, require_roles
from apps.accounts.models import Department, Member

from .forms import MailIntegrationSettingForm, MailIntegrationTestForm, MailRecipientGroupForm
from .models import MailIntegrationSetting, MailRecipientGroup, MailSendHistory


def _mail_nav_items():
    return [
        ("dashboard_index", "管理者ページ"),
        ("member_settings", "メンバー管理"),
        ("department_settings", "部署管理"),
        ("performance_index", "実績管理"),
        ("mail_integration_settings", "メール連携設定"),
        ("mail_group_settings", "メールグループ管理"),
        ("mail_history", "メール履歴"),
    ]


@require_roles(ROLE_ADMIN)
def mail_integration_settings(request: HttpRequest) -> HttpResponse:
    status_message = ""
    preview_recipients: list[str] = []
    preview_summary = ""
    setting, _ = MailIntegrationSetting.objects.get_or_create(
        pk=1,
        defaults={"sender_name": "獲得メール送信"},
    )

    if request.method == "POST" and request.POST.get("action") == "save_settings":
        existing_secret_values = {
            secret_field: getattr(setting, secret_field)
            for secret_field in ("client_id", "client_secret", "refresh_token")
        }
        form = MailIntegrationSettingForm(request.POST, instance=setting)
        test_form = MailIntegrationTestForm()
        if form.is_valid():
            updated_setting = form.save(commit=False)
            for secret_field in ("client_id", "client_secret", "refresh_token"):
                new_value = form.cleaned_data.get(secret_field)
                if not new_value:
                    setattr(updated_setting, secret_field, existing_secret_values[secret_field])
            updated_setting.save()
            status_message = "メール連携設定を更新しました。"
            setting = updated_setting
            form = MailIntegrationSettingForm(instance=setting)
        else:
            status_message = "入力内容を確認してください。"
    elif request.method == "POST" and request.POST.get("action") == "test_preview":
        form = MailIntegrationSettingForm(instance=setting)
        test_form = MailIntegrationTestForm(request.POST)
        if test_form.is_valid():
            target_type = test_form.cleaned_data["target_type"]
            if target_type == MailIntegrationTestForm.TARGET_MEMBER:
                member = test_form.cleaned_data["member"]
                preview_recipients = [f"{member.name} <{member.email}>"]
                preview_summary = "選択したメンバー1人にテスト送信する想定です。"
            else:
                group = test_form.cleaned_data["group"]
                members = group.members.exclude(email="").order_by("name")
                preview_recipients = [f"{member.name} <{member.email}>" for member in members]
                preview_summary = f"{group.name} に紐づくメンバーへテスト送信する想定です。"
            status_message = "テスト送信先のプレビューを更新しました。"
        else:
            status_message = "テスト送信先を確認してください。"
    else:
        form = MailIntegrationSettingForm(instance=setting)
        test_form = MailIntegrationTestForm()

    recent_test_histories = MailSendHistory.objects.filter(is_test=True).select_related(
        "recipient_group",
        "sender_member",
    )[:10]

    context = {
        "nav_items": _mail_nav_items(),
        "form": form,
        "test_form": test_form,
        "setting": setting,
        "status_message": status_message,
        "preview_recipients": preview_recipients,
        "preview_summary": preview_summary,
        "recent_test_histories": recent_test_histories,
    }
    return render(request, "mail/settings.html", context)


@require_roles(ROLE_ADMIN)
def mail_group_settings(request: HttpRequest) -> HttpResponse:
    status_message = ""
    groups = MailRecipientGroup.objects.prefetch_related("members", "related_departments").select_related("department").order_by("name")
    edit_group = None
    edit_group_id = request.GET.get("edit")
    if edit_group_id:
        edit_group = get_object_or_404(MailRecipientGroup, pk=edit_group_id)

    if request.method == "POST":
        group_id = request.POST.get("group_id")
        edit_group = get_object_or_404(MailRecipientGroup, pk=group_id) if group_id else None
        form = MailRecipientGroupForm(request.POST)
        if form.is_valid():
            group = edit_group or MailRecipientGroup()
            group.name = form.cleaned_data["name"]
            selected_departments = list(form.cleaned_data["departments"])
            group.department = selected_departments[0] if selected_departments else None
            group.is_active = form.cleaned_data["is_active"]
            group.save()
            group.related_departments.set(selected_departments)
            group.members.set(form.cleaned_data["members"])
            status_message = "メールグループを保存しました。"
            edit_group = None
            form = MailRecipientGroupForm()
        else:
            status_message = "入力内容を確認してください。"
    else:
        if edit_group:
            form = MailRecipientGroupForm(
                initial={
                    "name": edit_group.name,
                    "departments": list(edit_group.related_departments.values_list("id", flat=True))
                    or ([edit_group.department_id] if edit_group.department_id else []),
                    "members": edit_group.members.all(),
                    "is_active": edit_group.is_active,
                }
            )
        else:
            form = MailRecipientGroupForm()

    context = {
        "nav_items": _mail_nav_items(),
        "form": form,
        "groups": groups,
        "edit_group": edit_group,
        "status_message": status_message,
    }
    return render(request, "mail/group_settings.html", context)


@require_roles(ROLE_ADMIN)
def mail_group_member_options(request: HttpRequest) -> HttpResponse:
    raw_departments = request.GET.getlist("departments")
    department_ids = [int(value) for value in raw_departments if str(value).isdigit()]
    members = Member.objects.active().exclude(email="")
    if department_ids:
        members = members.filter(department_links__department_id__in=department_ids).distinct()
    members = members.order_by("name")
    return JsonResponse(
        {
            "members": [
                {
                    "id": member.id,
                    "name": member.name,
                    "email": member.email,
                    "departments": list(
                        Department.objects.filter(member_links__member=member, is_active=True)
                        .order_by("code")
                        .values_list("code", flat=True)
                    ),
                }
                for member in members
            ]
        }
    )


@require_roles(ROLE_ADMIN)
def mail_history(request: HttpRequest) -> HttpResponse:
    histories = MailSendHistory.objects.select_related(
        "department",
        "sender_member",
        "recipient_group",
    )
    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        histories = histories.filter(status=status_filter)
    paginator = Paginator(histories, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    context = {
        "nav_items": _mail_nav_items(),
        "page_obj": page_obj,
        "paginator": paginator,
        "histories": page_obj.object_list,
        "status_filter": status_filter,
        "status_choices": MailSendHistory.STATUS_CHOICES,
    }
    return render(request, "mail/history.html", context)
