from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.auth import ROLE_ADMIN, require_roles
from apps.accounts.models import Department, Member

from .forms import (
    MailDepartmentRoutingForm,
    MailIntegrationSettingForm,
    MailIntegrationTestForm,
    MailRecipientGroupForm,
)
from .models import MailDepartmentRouting, MailIntegrationSetting, MailRecipientGroup, MailSendHistory
from .services import send_test_mail


def _mail_nav_items():
    return [
        ("member_settings", "メンバー管理"),
        ("department_settings", "部署管理"),
        ("performance_index", "実績管理"),
        ("mail_group_settings", "メール"),
        ("target_index", "目標設定"),
        ("report_history", "保存報告一覧"),
    ]


@require_roles(ROLE_ADMIN)
def mail_integration_settings(request: HttpRequest) -> HttpResponse:
    return redirect("mail_group_settings")


@require_roles(ROLE_ADMIN)
def mail_group_settings(request: HttpRequest) -> HttpResponse:
    status_message = ""
    preview_recipients: list[str] = []
    preview_summary = ""
    groups = MailRecipientGroup.objects.prefetch_related("members", "related_departments").select_related("department").order_by("name")
    edit_group = None
    edit_group_id = request.GET.get("edit")
    if edit_group_id:
        edit_group = get_object_or_404(MailRecipientGroup, pk=edit_group_id)
    setting, _ = MailIntegrationSetting.objects.get_or_create(
        pk=1,
        defaults={"sender_name": "獲得メール送信"},
    )

    routing_departments = {
        department.code: department
        for department in Department.objects.filter(code__in=["UN", "WV"], is_active=True)
    }
    routing_map = {
        routing.department.code: routing.recipient_group_id
        for routing in MailDepartmentRouting.objects.filter(department__code__in=["UN", "WV"]).select_related("department")
    }

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_settings":
            existing_secret_values = {
                secret_field: getattr(setting, secret_field)
                for secret_field in ("client_id", "client_secret", "refresh_token")
            }
            form = MailRecipientGroupForm(
                initial={
                    "name": edit_group.name,
                    "departments": list(edit_group.related_departments.values_list("id", flat=True))
                    or ([edit_group.department_id] if edit_group and edit_group.department_id else []),
                    "members": edit_group.members.all() if edit_group else [],
                    "is_active": edit_group.is_active if edit_group else True,
                }
            ) if edit_group else MailRecipientGroupForm()
            routing_form = MailDepartmentRoutingForm(
                initial={
                    "un_group": routing_map.get("UN"),
                    "wv_group": routing_map.get("WV"),
                }
            )
            settings_form = MailIntegrationSettingForm(request.POST, instance=setting)
            test_form = MailIntegrationTestForm()
            if settings_form.is_valid():
                updated_setting = settings_form.save(commit=False)
                for secret_field in ("client_id", "client_secret", "refresh_token"):
                    new_value = settings_form.cleaned_data.get(secret_field)
                    if not new_value:
                        setattr(updated_setting, secret_field, existing_secret_values[secret_field])
                updated_setting.save()
                setting = updated_setting
                settings_form = MailIntegrationSettingForm(instance=setting)
                status_message = "メール連携設定を更新しました。"
            else:
                status_message = "入力内容を確認してください。"
        elif action in {"test_preview", "test_send"}:
            form = MailRecipientGroupForm(
                initial={
                    "name": edit_group.name,
                    "departments": list(edit_group.related_departments.values_list("id", flat=True))
                    or ([edit_group.department_id] if edit_group and edit_group.department_id else []),
                    "members": edit_group.members.all() if edit_group else [],
                    "is_active": edit_group.is_active if edit_group else True,
                }
            ) if edit_group else MailRecipientGroupForm()
            routing_form = MailDepartmentRoutingForm(
                initial={
                    "un_group": routing_map.get("UN"),
                    "wv_group": routing_map.get("WV"),
                }
            )
            settings_form = MailIntegrationSettingForm(instance=setting)
            test_form = MailIntegrationTestForm(request.POST)
            if test_form.is_valid():
                target_type = test_form.cleaned_data["target_type"]
                if target_type == MailIntegrationTestForm.TARGET_MEMBER:
                    member = test_form.cleaned_data["member"]
                    preview_recipients = [f"{member.name} <{member.email}>"]
                    preview_summary = "選択したメンバー1人にテスト送信する想定です。"
                    target_member = member
                    target_group = None
                else:
                    group = test_form.cleaned_data["group"]
                    members = group.members.exclude(email="").order_by("name")
                    preview_recipients = [f"{member.name} <{member.email}>" for member in members]
                    preview_summary = f"{group.name} に紐づくメンバーへテスト送信する想定です。"
                    target_member = None
                    target_group = group
                if action == "test_send":
                    history = send_test_mail(
                        target_member=target_member,
                        recipient_group=target_group,
                    )
                    if history.status == MailSendHistory.STATUS_SENT:
                        status_message = "テスト送信を実行しました。"
                    else:
                        status_message = f"テスト送信に失敗しました: {history.error_message or history.error_code or '送信エラー'}"
                else:
                    status_message = "テスト送信先のプレビューを更新しました。"
            else:
                status_message = "テスト送信先を確認してください。"
        elif action == "save_routing":
            form = MailRecipientGroupForm(
                initial={
                    "name": edit_group.name,
                    "departments": list(edit_group.related_departments.values_list("id", flat=True))
                    or ([edit_group.department_id] if edit_group and edit_group.department_id else []),
                    "members": edit_group.members.all() if edit_group else [],
                    "is_active": edit_group.is_active if edit_group else True,
                }
            ) if edit_group else MailRecipientGroupForm()
            routing_form = MailDepartmentRoutingForm(request.POST)
            settings_form = MailIntegrationSettingForm(instance=setting)
            test_form = MailIntegrationTestForm()
            if routing_form.is_valid():
                for code, field_name in (("UN", "un_group"), ("WV", "wv_group")):
                    department = routing_departments.get(code)
                    if not department:
                        continue
                    group = routing_form.cleaned_data.get(field_name)
                    if group:
                        MailDepartmentRouting.objects.update_or_create(
                            department=department,
                            defaults={"recipient_group": group},
                        )
                    else:
                        MailDepartmentRouting.objects.filter(department=department).delete()
                status_message = "決済報告の既定メールグループを更新しました。"
                routing_map = {
                    routing.department.code: routing.recipient_group_id
                    for routing in MailDepartmentRouting.objects.filter(department__code__in=["UN", "WV"]).select_related("department")
                }
                routing_form = MailDepartmentRoutingForm(
                    initial={
                        "un_group": routing_map.get("UN"),
                        "wv_group": routing_map.get("WV"),
                    }
                )
            else:
                status_message = "決済報告グループの設定を確認してください。"
        else:
            group_id = request.POST.get("group_id")
            edit_group = get_object_or_404(MailRecipientGroup, pk=group_id) if group_id else None
            form = MailRecipientGroupForm(request.POST)
            routing_form = MailDepartmentRoutingForm(
                initial={
                    "un_group": routing_map.get("UN"),
                    "wv_group": routing_map.get("WV"),
                }
            )
            settings_form = MailIntegrationSettingForm(instance=setting)
            test_form = MailIntegrationTestForm()
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
        routing_form = MailDepartmentRoutingForm(
            initial={
                "un_group": routing_map.get("UN"),
                "wv_group": routing_map.get("WV"),
            }
        )
        settings_form = MailIntegrationSettingForm(instance=setting)
        test_form = MailIntegrationTestForm()

    recent_test_histories = MailSendHistory.objects.filter(is_test=True).select_related(
        "recipient_group",
        "sender_member",
    )[:10]

    context = {
        "nav_items": _mail_nav_items(),
        "form": form,
        "routing_form": routing_form,
        "settings_form": settings_form,
        "test_form": test_form,
        "setting": setting,
        "preview_recipients": preview_recipients,
        "preview_summary": preview_summary,
        "recent_test_histories": recent_test_histories,
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


@require_roles(ROLE_ADMIN)
def mail_group_delete(request: HttpRequest, group_id: int) -> HttpResponse:
    group = get_object_or_404(MailRecipientGroup, pk=group_id)
    if request.method == "POST":
        MailDepartmentRouting.objects.filter(recipient_group=group).delete()
        group.delete()
    return redirect("mail_group_settings")
