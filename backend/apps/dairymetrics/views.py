from urllib.parse import urlencode

from django.contrib.auth import login as auth_login, logout as auth_logout
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Department, Member
from apps.common.target_periods import current_active_period, period_options_active_first
from apps.mail.models import MailSendHistory
from apps.mail.services import MailSendError, record_transaction_mail_failure, send_transaction_mail
from apps.targets.models import Period, TARGET_STATUS_PLANNED
from apps.testimony.services.notifications import unread_recent_article_notification
from apps.talks.services.notifications import unread_recent_post_notification

from .auth import get_member_profile, require_dairymetrics_admin, require_dairymetrics_member
from .forms import (
    DairyMetricsLoginForm,
    DairymetricsV2CloseoutForm,
    DairymetricsV2DepartmentTargetForm,
    DairymetricsV2PersonalSetupForm,
    DairymetricsV2TransactionForm,
)
from .services.entry_context import (
    build_entry_v2_transaction_demo_context,
    member_departments,
    parse_month_input,
    resolve_metrics_v2_department,
)
from .models import MemberDailyMetricEntry, MemberMetricTransaction, MemberMetricTransactionReaction, MetricAdjustment
from .services.entry_v2 import (
    build_transaction_mail_preview,
    build_v2_redirect_url,
    find_duplicate_transaction,
    get_default_mail_group,
    get_or_create_department_daily_summary,
    transaction_mail_status,
)
from .services.metrics_v2 import build_metrics_v2_dashboard_payload, resolve_metrics_v2_scope
from .services.reports import build_metrics_scope_report
from .services.report_exports import build_report_ai_text, build_report_export_payload
from .services.reaction_notifications import (
    mark_transaction_reaction_notifications_seen,
    unread_transaction_reaction_notification,
)
from .services.transaction_notifications import (
    mark_today_transaction_notifications_seen,
    unread_today_transaction_notification,
)
ENTRY_V2_AGE_BANDS = [
    {"key": "teens", "label": "10代"},
    {"key": "twenties", "label": "20代"},
    {"key": "thirties", "label": "30代"},
    {"key": "forties", "label": "40代"},
    {"key": "fifties", "label": "50代"},
    {"key": "sixties", "label": "60代"},
    {"key": "seventies", "label": "70代"},
    {"key": "eighties", "label": "80代"},
    {"key": "nineties_or_older", "label": "90代以上"},
]
ENTRY_V2_GENDER_BANDS = [
    {"key": "male", "label": "男性"},
    {"key": "female", "label": "女性"},
]
ENTRY_V2_NATIONALITY_BANDS = [
    {"key": "domestic", "label": "国内"},
    {"key": "overseas", "label": "海外"},
]


ENTRY_V2_TARGET_COUNT_OPTIONS = [1, 2, 3, 4, 5]
ENTRY_V2_TARGET_AMOUNT_OPTIONS = list(range(1000, 10001, 500))
ENTRY_V2_DEPARTMENT_TARGET_AMOUNT_OPTIONS = list(range(15000, 30001, 1000))
ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS = list(range(1000, 5001, 500))
ENTRY_V2_WV_REFUGEE_AMOUNT_OPTIONS = list(range(500, 4001, 500))


def _current_period_scope_period(*, today):
    """Current-period screens must never default to finished periods."""
    return current_active_period(target_date=today)


def _requested_or_current_period(request: HttpRequest, *, today):
    raw_period_id = (request.GET.get("period_id") or "").strip()
    if raw_period_id.isdigit():
        requested_period = Period.objects.exclude(status=TARGET_STATUS_PLANNED).filter(pk=int(raw_period_id)).first()
        if requested_period:
            return requested_period
    return _current_period_scope_period(today=today)


def _login_redirect_url(user, *, fallback=""):
    if fallback:
        return fallback
    if user.is_staff:
        return reverse("performance_index")
    return reverse("performance_member_dashboard")


def _member_directory_queryset():
    return (
        Member.objects.filter(department_links__department__is_active=True)
        .distinct()
        .order_by("name")
        .prefetch_related("department_links__department")
    )


def _render_personal_setup_form_partial(request: HttpRequest, context: dict, *, inline: bool) -> str:
    partial_context = {
        **context,
        "department_select_id": "v2-inline-personal-department" if inline else "v2-personal-department",
        "entry_date_id": "v2-inline-personal-date" if inline else "v2-personal-date",
        "location_id": "v2-inline-personal-location" if inline else "v2-personal-location",
        "cs_count_id": "v2-inline-personal-cs-count" if inline else "v2-personal-target-cs-count",
        "refugee_count_id": "v2-inline-personal-refugee-count" if inline else "v2-personal-target-refugee-count",
        "count_select_id": "v2-inline-personal-count-select" if inline else "v2-personal-target-count-select",
        "count_hidden_id": "v2-inline-personal-count-hidden" if inline else "v2-personal-target-count-hidden",
        "count_wrap_id": "v2-inline-personal-count-wrap" if inline else "v2-personal-target-count-wrap",
        "count_custom_id": "v2-inline-personal-count-custom" if inline else "v2-personal-target-count-custom",
        "amount_select_id": "v2-inline-personal-amount-select" if inline else "v2-personal-target-amount-select",
        "amount_hidden_id": "v2-inline-personal-amount-hidden" if inline else "v2-personal-target-amount-hidden",
        "amount_wrap_id": "v2-inline-personal-amount-wrap" if inline else "v2-personal-target-amount-wrap",
        "amount_custom_id": "v2-inline-personal-amount-custom" if inline else "v2-personal-target-amount-custom",
        "submit_label": "修正内容を保存" if inline else "個人の準備を保存",
        "close_button_label": "閉じる" if inline else "",
        "close_button_attr": "data-close-personal-target-edit" if inline else "",
    }
    return render_to_string(
        "dairymetrics/partials/personal_setup_form.html",
        partial_context,
        request=request,
    )


def _render_department_target_form_partial(request: HttpRequest, context: dict, *, inline: bool) -> str:
    partial_context = {
        **context,
        "entry_date_id": "v2-inline-target-date" if inline else "v2-dept-target-date",
        "amount_select_id": "v2-inline-target-amount-select" if inline else "v2-dept-target-amount-select",
        "amount_hidden_id": "v2-inline-target-amount-hidden" if inline else "v2-dept-target-amount-hidden",
        "amount_wrap_id": "v2-inline-target-amount-wrap" if inline else "v2-dept-target-amount-wrap",
        "amount_custom_id": "v2-inline-target-amount-custom" if inline else "v2-dept-target-amount-custom",
        "submit_label": "修正内容を保存" if inline else "全体目標を保存",
        "close_button_label": "閉じる" if inline else "",
        "close_button_attr": "data-close-department-target-edit" if inline else "",
        "show_meta": not inline,
    }
    return render_to_string(
        "dairymetrics/partials/department_target_form.html",
        partial_context,
        request=request,
    )

def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect(_login_redirect_url(request.user))

    form = DairyMetricsLoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.user)
        return redirect(_login_redirect_url(form.user, fallback=request.POST.get("next", "")))
    return render(request, "dairymetrics/login.html", {"form": form, "next": request.GET.get("next", "")})


def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    return redirect("performance_login")


@require_dairymetrics_member
def metrics_v2_demo(request: HttpRequest) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    departments, selected_department = resolve_metrics_v2_department(request=request, member=viewer_member)
    if not selected_department:
        return redirect(_login_redirect_url(request.user))
    selected_member = None
    raw_member_id = (request.GET.get("member") or "").strip()
    if request.user.is_staff and raw_member_id.isdigit():
        selected_member = (
            _member_directory_queryset()
            .filter(pk=int(raw_member_id), department_links__department=selected_department)
            .distinct()
            .first()
        )

    today = timezone.localdate()
    requested_scope = (request.GET.get("scope") or "recent").strip()
    requested_month = parse_month_input(request.GET.get("month") or "")
    available_periods = period_options_active_first(target_date=today, limit=18)
    requested_period = None
    if requested_scope == "period":
        requested_period = _requested_or_current_period(request, today=today)
    requested_start_date = parse_date((request.GET.get("start_date") or "").strip())
    requested_end_date = parse_date((request.GET.get("end_date") or "").strip())

    scope = resolve_metrics_v2_scope(
        today=today,
        scope=requested_scope,
        requested_month=requested_month,
        requested_period=requested_period,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
    )
    payload = build_metrics_v2_dashboard_payload(
        department=selected_department,
        scope=scope,
        member=selected_member if request.user.is_staff else viewer_member,
    )
    ranking_metric_map = payload.get("ranking", {}).get("metric_map", {})
    for metric_payload in ranking_metric_map.values():
        detail_urls = []
        for row in metric_payload.get("rows", []):
            detail_url = reverse(
                "performance_member_insight",
                args=[row["member_id"], selected_department.id],
            )
            row["detail_url"] = detail_url
            detail_urls.append(detail_url)
        metric_payload["detail_urls"] = detail_urls
    payload_json = {**payload, "scope": {"scope": scope.scope, "label": scope.label}}
    context = {
        "is_admin": request.user.is_staff,
        "member": viewer_member,
        "selected_member": selected_member,
        "selected_department": selected_department,
        "departments": departments,
        "scope": scope,
        "scope_value": scope.scope,
        "month_value": (scope.month_start or today.replace(day=1)).strftime("%Y-%m"),
        "start_date_value": scope.start_date.strftime("%Y-%m-%d"),
        "end_date_value": scope.end_date.strftime("%Y-%m-%d"),
        "period_options": available_periods,
        "selected_period_id": scope.period.id if scope.period else "",
        "metrics_v2_payload": payload,
        "metrics_v2_payload_json": payload_json,
    }
    return render(request, "dairymetrics/metrics_v2.html", context)


def _metrics_report_data(request):
    viewer_member = get_member_profile(request.user)
    departments, selected_department = resolve_metrics_v2_department(request=request, member=viewer_member)
    if not selected_department:
        return None

    today = timezone.localdate()
    requested_scope = (request.GET.get("scope") or "month").strip()
    if requested_scope not in {"month", "period"}:
        requested_scope = "month"
    requested_month = parse_month_input(request.GET.get("month") or "")
    period_options = period_options_active_first(target_date=today)
    requested_period = None
    if requested_scope == "period":
        requested_period = _requested_or_current_period(request, today=today)

    scope = resolve_metrics_v2_scope(
        today=today,
        scope=requested_scope,
        requested_month=requested_month,
        requested_period=requested_period,
    )
    if requested_scope == "period" and scope.scope != "period":
        scope = resolve_metrics_v2_scope(today=today, scope="month", requested_month=requested_month)

    report = build_metrics_scope_report(department=selected_department, scope=scope)
    export_query = urlencode(
        {
            "department": selected_department.code,
            "scope": scope.scope,
            "month": (scope.month_start or today.replace(day=1)).strftime("%Y-%m"),
            "period_id": scope.period.id if scope.period else "",
        }
    )
    return {
        "is_admin": request.user.is_staff,
        "member": viewer_member,
        "departments": departments,
        "selected_department": selected_department,
        "scope": scope,
        "scope_value": scope.scope,
        "month_value": (scope.month_start or today.replace(day=1)).strftime("%Y-%m"),
        "period_options": period_options,
        "selected_period_id": scope.period.id if scope.period else "",
        "report": report,
        "report_export_query": export_query,
    }


@require_dairymetrics_member
def metrics_report(request: HttpRequest) -> HttpResponse:
    context = _metrics_report_data(request)
    if context is None:
        return redirect(_login_redirect_url(request.user))
    return render(request, "dairymetrics/metrics_report.html", context)


@require_dairymetrics_member
def metrics_report_export(request: HttpRequest) -> HttpResponse:
    context = _metrics_report_data(request)
    if context is None:
        return redirect(_login_redirect_url(request.user))

    payload = build_report_export_payload(
        department=context["selected_department"],
        scope=context["scope"],
        report=context["report"],
    )
    export_format = (request.GET.get("format") or "txt").strip().lower()
    filename_base = (
        f"metrics-report-{context['selected_department'].code}-"
        f"{context['scope'].start_date:%Y%m%d}-{context['scope'].end_date:%Y%m%d}"
    )
    if export_format == "json":
        response = JsonResponse(
            payload,
            json_dumps_params={"ensure_ascii": False, "indent": 2},
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_base}.json"'
        return response

    response = HttpResponse(
        build_report_ai_text(payload),
        content_type="text/plain; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename_base}.txt"'
    return response


@require_dairymetrics_member
def entry_v2_personal_setup_fields(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return JsonResponse({"error": "member_not_found"}, status=404)

    department_id = (request.GET.get("department") or "").strip()
    selected_department_obj = None
    if department_id.isdigit():
        selected_department_obj = (
            Department.objects.filter(
                is_active=True,
                pk=int(department_id),
                member_links__member=member,
            )
            .distinct()
            .first()
        )
    selected_department_code = selected_department_obj.code if selected_department_obj else ""
    entry_date = parse_date((request.GET.get("entry_date") or "").strip()) or timezone.localdate()
    department_entry_date = parse_date((request.GET.get("department_entry_date") or "").strip()) or entry_date
    form_initial = {
        "department": selected_department_obj,
        "entry_date": entry_date,
        "location_name": (request.GET.get("location_name") or "").strip(),
        "daily_target_count": (request.GET.get("daily_target_count") or "").strip() or 0,
        "daily_target_cs_count": (request.GET.get("daily_target_cs_count") or "").strip() or 0,
        "daily_target_refugee_count": (request.GET.get("daily_target_refugee_count") or "").strip() or 0,
        "daily_target_amount": (request.GET.get("personal_daily_target_amount") or "").strip() or 0,
    }
    personal_setup_form = DairymetricsV2PersonalSetupForm(member=member, initial=form_initial)
    department_target_form = DairymetricsV2DepartmentTargetForm(
        initial={
            "entry_date": department_entry_date,
            "daily_target_amount": (request.GET.get("department_daily_target_amount") or "").strip() or 0,
        }
    )
    context = build_entry_v2_transaction_demo_context(
        member=member,
        selected_department=selected_department_code,
        entry_date=entry_date,
        personal_setup_form=personal_setup_form,
        department_target_form=department_target_form,
        age_bands=ENTRY_V2_AGE_BANDS,
        gender_bands=ENTRY_V2_GENDER_BANDS,
        nationality_bands=ENTRY_V2_NATIONALITY_BANDS,
        target_count_options=ENTRY_V2_TARGET_COUNT_OPTIONS,
        target_amount_options=ENTRY_V2_TARGET_AMOUNT_OPTIONS,
        department_target_amount_options=ENTRY_V2_DEPARTMENT_TARGET_AMOUNT_OPTIONS,
        transaction_amount_options=ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS,
        wv_refugee_amount_options=ENTRY_V2_WV_REFUGEE_AMOUNT_OPTIONS,
    )
    return JsonResponse(
        {
            "setup_html": _render_personal_setup_form_partial(request, context, inline=False),
            "inline_html": _render_personal_setup_form_partial(request, context, inline=True),
            "department_target_html": _render_department_target_form_partial(request, context, inline=False),
            "department_target_inline_html": _render_department_target_form_partial(request, context, inline=True),
            "is_wv": context["selected_department_is_wv"],
        }
    )


@require_dairymetrics_member
def entry_form_v2_transaction_demo(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect(_login_redirect_url(request.user))

    raw_department_code = (
        request.POST.get("department_code")
        or request.POST.get("department")
        or request.GET.get("department")
        or ""
    ).strip()
    raw_entry_date = (
        request.POST.get("entry_date")
        or request.POST.get("target_entry_date")
        or request.GET.get("date")
        or ""
    ).strip()
    entry_date = parse_date(raw_entry_date) or timezone.localdate()
    selected_department = raw_department_code

    status_message = ""
    duplicate_transaction = None
    open_entry_panel = False
    open_personal_target_panel = False
    open_department_target_panel = False
    open_closeout_panel = False
    personal_setup_form = None
    department_target_form = None
    transaction_form = None
    closeout_form = None
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        selected_department = raw_department_code
        selected_department_obj = Department.objects.filter(
            is_active=True,
            code=selected_department,
            member_links__member=member,
        ).distinct().first()

        if action == "save_personal_setup":
            personal_setup_form = DairymetricsV2PersonalSetupForm(request.POST, member=member)
            if personal_setup_form.is_valid():
                selected_department_obj = personal_setup_form.cleaned_data["department"]
                selected_department = selected_department_obj.code
                entry_date = personal_setup_form.cleaned_data["entry_date"]
                entry, _ = MemberDailyMetricEntry.objects.get_or_create(
                    member=member,
                    department=selected_department_obj,
                    entry_date=entry_date,
                    defaults={"input_source": MemberDailyMetricEntry.SOURCE_MEMBER},
                )
                entry.daily_target_count = personal_setup_form.cleaned_data["daily_target_count"]
                entry.daily_target_cs_count = personal_setup_form.cleaned_data.get("daily_target_cs_count") or 0
                entry.daily_target_refugee_count = personal_setup_form.cleaned_data.get("daily_target_refugee_count") or 0
                entry.daily_target_amount = personal_setup_form.cleaned_data["daily_target_amount"]
                entry.location_name = personal_setup_form.cleaned_data["location_name"]
                entry.input_source = MemberDailyMetricEntry.SOURCE_MEMBER
                entry.save(
                    update_fields=[
                        "daily_target_count",
                        "daily_target_cs_count",
                        "daily_target_refugee_count",
                        "daily_target_amount",
                        "location_name",
                        "input_source",
                        "updated_at",
                    ]
                )
                get_or_create_department_daily_summary(
                    department=selected_department_obj,
                    entry_date=entry_date,
                    member=member,
                )
                return redirect(
                    build_v2_redirect_url(
                        department_code=selected_department,
                        entry_date=entry_date,
                        saved="personal_setup",
                    )
                )
            selected_department_obj = personal_setup_form.fields["department"].queryset.filter(
                pk=request.POST.get("department")
            ).first()
            if selected_department_obj:
                selected_department = selected_department_obj.code
            status_message = "個人の日目標を確認してください。"
            open_personal_target_panel = True
        elif action == "save_department_target":
            if not selected_department_obj:
                status_message = "部署を選択してください。"
            else:
                department_target_form = DairymetricsV2DepartmentTargetForm(request.POST)
                if department_target_form.is_valid():
                    entry_date = department_target_form.cleaned_data["entry_date"]
                    summary = get_or_create_department_daily_summary(
                        department=selected_department_obj,
                        entry_date=entry_date,
                        member=member,
                    )
                    summary.daily_target_amount = department_target_form.cleaned_data["daily_target_amount"]
                    if summary.created_by_id is None:
                        summary.created_by = member
                    summary.updated_by = member
                    summary.save(update_fields=["daily_target_amount", "created_by", "updated_by", "updated_at"])
                    return redirect(
                        build_v2_redirect_url(
                            department_code=selected_department,
                            entry_date=entry_date,
                            saved="department_target",
                        )
                    )
                status_message = "部署全体の日目標を確認してください。"
                open_department_target_panel = True
        elif action in {"save_transaction", "save_transaction_preview"}:
            if not selected_department_obj:
                status_message = "部署を選択してください。"
            else:
                transaction_id = (request.POST.get("transaction_id") or "").strip()
                transaction_instance = None
                if transaction_id.isdigit():
                    transaction_instance = (
                        MemberMetricTransaction.objects.filter(
                            id=int(transaction_id),
                            entry__member=member,
                            entry__department=selected_department_obj,
                            entry__entry_date=entry_date,
                        )
                        .select_related("entry")
                        .first()
                    )
                transaction_form = DairymetricsV2TransactionForm(
                    request.POST,
                    instance=transaction_instance,
                    department=selected_department_obj,
                )
                if transaction_form.is_valid():
                    entry, _ = MemberDailyMetricEntry.objects.get_or_create(
                        member=member,
                        department=selected_department_obj,
                        entry_date=entry_date,
                        defaults={"input_source": MemberDailyMetricEntry.SOURCE_MEMBER},
                    )
                    duplicate_transaction = find_duplicate_transaction(
                        entry=entry,
                        cleaned_data=transaction_form.cleaned_data,
                        exclude_id=transaction_instance.id if transaction_instance else None,
                    )
                    if duplicate_transaction is not None:
                        status_message = "同じ内容の決済が既に登録されています。登録は行わず、必要なら既存決済からメールだけ送信してください。"
                        open_entry_panel = True
                    else:
                        transaction_obj = transaction_form.save(commit=False)
                        transaction_obj.entry = entry
                        transaction_obj.save()
                        return redirect(
                            build_v2_redirect_url(
                                department_code=selected_department,
                                entry_date=entry_date,
                                saved="transaction",
                                preview_tx=transaction_obj.id if action == "save_transaction_preview" else None,
                            )
                        )
                else:
                    status_message = "決済明細を確認してください。"
                    open_entry_panel = True
        elif action == "delete_transaction":
            transaction_id = (request.POST.get("transaction_id") or "").strip()
            if not selected_department_obj:
                status_message = "削除対象の決済を確認してください。"
            elif not transaction_id.isdigit():
                status_message = "削除対象の決済を確認してください。"
            else:
                transaction_obj = (
                    MemberMetricTransaction.objects.filter(
                        id=int(transaction_id),
                        entry__member=member,
                        entry__department=selected_department_obj,
                        entry__entry_date=entry_date,
                    )
                    .select_related("entry", "entry__department", "entry__member")
                    .first()
                )
                if not transaction_obj:
                    status_message = "削除対象の決済が見つかりません。"
                else:
                    transaction_obj.delete()
                    return redirect(
                        build_v2_redirect_url(
                            department_code=selected_department,
                            entry_date=entry_date,
                            saved="transaction_deleted",
                        )
                    )
        elif action in {"send_transaction_mock", "send_transaction_mail", "send_duplicate_transaction_mail"}:
            preview_tx_id = (request.POST.get("preview_transaction_id") or "").strip()
            preview_history_id = (request.POST.get("preview_history_id") or "").strip()
            duplicate_tx_id = (request.POST.get("duplicate_transaction_id") or "").strip()
            edited_subject = (request.POST.get("preview_subject") or "").strip()
            edited_body = (request.POST.get("preview_body") or "").strip()
            if not selected_department_obj:
                status_message = "送信対象の決済を確認してください。"
            else:
                preview_transaction = None
                if action == "send_duplicate_transaction_mail" and duplicate_tx_id.isdigit():
                    preview_transaction = (
                        MemberMetricTransaction.objects.filter(
                            id=int(duplicate_tx_id),
                            entry__member=member,
                            entry__department=selected_department_obj,
                            entry__entry_date=entry_date,
                        )
                        .select_related("entry", "entry__department")
                        .first()
                    )
                elif preview_tx_id.isdigit():
                    preview_transaction = (
                        MemberMetricTransaction.objects.filter(
                            id=int(preview_tx_id),
                            entry__member=member,
                            entry__department=selected_department_obj,
                            entry__entry_date=entry_date,
                        )
                        .select_related("entry", "entry__department")
                        .first()
                    )
                elif preview_history_id.isdigit():
                    history_obj = (
                        MailSendHistory.objects.filter(
                            id=int(preview_history_id),
                            department=selected_department_obj,
                            activity_date=entry_date,
                            is_test=False,
                        )
                        .select_related("transaction", "transaction__entry", "transaction__entry__department")
                        .first()
                    )
                    if history_obj:
                        preview_transaction = history_obj.transaction
                if not preview_transaction:
                    status_message = "送信対象の決済が見つかりません。"
                else:
                    existing_history = None
                    if preview_history_id.isdigit():
                        existing_history = (
                            MailSendHistory.objects.filter(
                                id=int(preview_history_id),
                                transaction=preview_transaction,
                                is_test=False,
                            )
                            .select_related("transaction")
                            .first()
                        )
                    recipient_group = get_default_mail_group(department=selected_department_obj)
                    preview_context = build_entry_v2_transaction_demo_context(
                        member=member,
                        selected_department=selected_department,
                        entry_date=entry_date,
                        preview_transaction=preview_transaction,
                        age_bands=ENTRY_V2_AGE_BANDS,
                        gender_bands=ENTRY_V2_GENDER_BANDS,
                        nationality_bands=ENTRY_V2_NATIONALITY_BANDS,
                        target_count_options=ENTRY_V2_TARGET_COUNT_OPTIONS,
                        target_amount_options=ENTRY_V2_TARGET_AMOUNT_OPTIONS,
                        department_target_amount_options=ENTRY_V2_DEPARTMENT_TARGET_AMOUNT_OPTIONS,
                        transaction_amount_options=ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS,
                        wv_refugee_amount_options=ENTRY_V2_WV_REFUGEE_AMOUNT_OPTIONS,
                    )
                    preview_payload = preview_context["preview_payload"] or build_transaction_mail_preview(
                        member=member,
                        department_code=selected_department,
                        transaction_obj=preview_transaction,
                        progress_cards=preview_context["progress_cards"],
                    )
                    subject = edited_subject or preview_payload["subject"]
                    body = edited_body or preview_payload["body"]
                    try:
                        send_transaction_mail(
                            sender_member=member,
                            transaction=preview_transaction,
                            recipient_group=recipient_group,
                            subject=subject,
                            body=body,
                            existing_history=existing_history,
                        )
                    except Exception as exc:
                        error_code = exc.code if isinstance(exc, MailSendError) else exc.__class__.__name__
                        error_message = exc.detail if isinstance(exc, MailSendError) else str(exc)
                        record_transaction_mail_failure(
                            sender_member=member,
                            transaction=preview_transaction,
                            recipient_group=recipient_group,
                            subject=subject,
                            body=body,
                            existing_history=existing_history,
                            error_code=error_code,
                            error_message=error_message,
                        )
                        return redirect(
                            build_v2_redirect_url(
                                department_code=selected_department,
                                entry_date=entry_date,
                                saved="mail_failed",
                            )
                        )
                    return redirect(
                        build_v2_redirect_url(
                            department_code=selected_department,
                            entry_date=entry_date,
                            saved="mail_sent",
                        )
                    )
        elif action == "save_closeout":
            if not selected_department_obj:
                status_message = "部署を選択してください。"
            else:
                entry = MemberDailyMetricEntry.objects.filter(
                    member=member,
                    department=selected_department_obj,
                    entry_date=entry_date,
                ).first()
                if not entry:
                    status_message = "先に決済を登録してください。"
                    open_closeout_panel = True
                else:
                    closeout_form = DairymetricsV2CloseoutForm(request.POST, instance=entry)
                    if closeout_form.is_valid():
                        closeout_entry = closeout_form.save(commit=False)
                        closeout_entry.activity_closed = True
                        closeout_entry.activity_closed_at = timezone.now()
                        closeout_entry.input_source = MemberDailyMetricEntry.SOURCE_MEMBER
                        closeout_entry.save(
                            update_fields=[
                                "approach_count",
                                "communication_count",
                                "memo",
                                "activity_closed",
                                "activity_closed_at",
                                "input_source",
                                "updated_at",
                            ]
                        )
                        summary = get_or_create_department_daily_summary(
                            department=selected_department_obj,
                            entry_date=entry_date,
                            member=member,
                        )
                        summary.recalculate_from_entries()
                        return redirect(
                            build_v2_redirect_url(
                                department_code=selected_department,
                                entry_date=entry_date,
                                saved="closeout",
                            )
                        )
                    status_message = "最終実績の入力内容を確認してください。"
                    open_closeout_panel = True

    preview_transaction = None
    preview_tx_id = request.GET.get("preview_tx")
    if preview_tx_id and preview_tx_id.isdigit():
        preview_transaction = (
            MemberMetricTransaction.objects.filter(
                id=int(preview_tx_id),
                entry__member=member,
                entry__department__code=selected_department,
                entry__entry_date=entry_date,
            )
            .select_related("entry", "entry__department")
            .first()
        )

    if not status_message:
        saved = (request.GET.get("saved") or "").strip()
        status_message = {
            "personal_setup": "個人の日目標を保存しました。",
            "department_target": "部署全体の日目標を保存しました。",
            "transaction": "決済明細を登録しました。",
            "transaction_deleted": "決済明細を削除しました。",
            "mail_sent": "メール履歴を保存しました。",
            "mail_failed": "メール送信に失敗しました。復旧後に再送してください。",
            "closeout": "活動終了時の最終実績を保存しました。",
        }.get(saved, "")

    context = build_entry_v2_transaction_demo_context(
        member=member,
        selected_department=selected_department,
        entry_date=entry_date,
        personal_setup_form=personal_setup_form,
        department_target_form=department_target_form,
        transaction_form=transaction_form,
        closeout_form=closeout_form,
        status_message=status_message,
        open_entry_panel=open_entry_panel,
        open_personal_target_panel=open_personal_target_panel,
        open_department_target_panel=open_department_target_panel,
        open_closeout_panel=open_closeout_panel,
        preview_transaction=preview_transaction,
        age_bands=ENTRY_V2_AGE_BANDS,
        gender_bands=ENTRY_V2_GENDER_BANDS,
        nationality_bands=ENTRY_V2_NATIONALITY_BANDS,
        target_count_options=ENTRY_V2_TARGET_COUNT_OPTIONS,
        target_amount_options=ENTRY_V2_TARGET_AMOUNT_OPTIONS,
        department_target_amount_options=ENTRY_V2_DEPARTMENT_TARGET_AMOUNT_OPTIONS,
        transaction_amount_options=ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS,
        wv_refugee_amount_options=ENTRY_V2_WV_REFUGEE_AMOUNT_OPTIONS,
    )
    if duplicate_transaction is not None:
        context["duplicate_transaction"] = {
            "id": duplicate_transaction.id,
            "amount": int(duplicate_transaction.support_amount or 0),
            "time_label": timezone.localtime(duplicate_transaction.created_at).strftime("%H:%M"),
            "mail_status": transaction_mail_status(duplicate_transaction),
        }
    reaction_notification_query = request.GET.copy()
    if selected_department:
        reaction_notification_query["department"] = selected_department
    reaction_notification_query["date"] = entry_date.strftime("%Y-%m-%d")
    reaction_notification_query["reaction_notifications"] = "1"
    reaction_notification_url = (
        f"{reverse('dairymetrics_entry_v2_transaction_demo')}?"
        f"{reaction_notification_query.urlencode()}#dairymetrics-v2-transaction-list"
    )
    reaction_notification = unread_transaction_reaction_notification(
        member=member,
        url=reaction_notification_url,
    )
    reaction_notification_open = request.GET.get("reaction_notifications") == "1"
    if reaction_notification_open:
        mark_transaction_reaction_notifications_seen(member=member)
    context["reaction_notification"] = reaction_notification
    context["reaction_notification_open"] = reaction_notification_open
    today = timezone.localdate()
    transaction_notification_query = request.GET.copy()
    if selected_department:
        transaction_notification_query["department"] = selected_department
    transaction_notification_query["date"] = today.strftime("%Y-%m-%d")
    transaction_notification_query["transaction_notifications"] = "1"
    transaction_notification_url = (
        f"{reverse('dairymetrics_entry_v2_transaction_demo')}?"
        f"{transaction_notification_query.urlencode()}#dairymetrics-v2-transaction-list"
    )
    transaction_notification = unread_today_transaction_notification(
        member=member,
        url=transaction_notification_url,
        today=today,
    )
    transaction_notification_open = request.GET.get("transaction_notifications") == "1"
    if transaction_notification_open:
        mark_today_transaction_notifications_seen(member=member)
    context["transaction_notification"] = transaction_notification
    context["transaction_notification_open"] = transaction_notification_open
    context["testimony_notification"] = unread_recent_article_notification(user=request.user)
    context["talks_notification"] = unread_recent_post_notification(user=request.user)
    return render(request, "dairymetrics/entry_form_v2_transaction.html", context)


@require_dairymetrics_member
def transaction_reaction_update(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POSTで送信してください。"}, status=405)

    member = get_member_profile(request.user)
    if member is None:
        return JsonResponse({"ok": False, "error": "メンバー情報が見つかりません。"}, status=403)

    reaction_type = (request.POST.get("reaction_type") or "").strip()
    reaction_labels = dict(MemberMetricTransactionReaction.REACTION_CHOICES)
    if reaction_type not in reaction_labels:
        return JsonResponse({"ok": False, "error": "リアクション種別を確認してください。"}, status=400)

    transaction_id = (request.POST.get("transaction_id") or "").strip()
    if not transaction_id.isdigit():
        return JsonResponse({"ok": False, "error": "対象の決済を確認してください。"}, status=400)

    transaction_obj = get_object_or_404(
        MemberMetricTransaction.objects.select_related("entry", "entry__department"),
        id=int(transaction_id),
    )
    allowed_department_ids = {department.id for department in member_departments(member)}
    if transaction_obj.entry.department_id not in allowed_department_ids:
        return JsonResponse({"ok": False, "error": "対象部署の決済ではありません。"}, status=403)

    MemberMetricTransactionReaction.objects.update_or_create(
        transaction=transaction_obj,
        member=member,
        defaults={"reaction_type": reaction_type},
    )
    reaction_rows = (
        MemberMetricTransactionReaction.objects.filter(transaction=transaction_obj)
        .values("reaction_type")
        .annotate(count=Count("id"))
    )
    counts = {reaction_key: 0 for reaction_key in reaction_labels}
    for row in reaction_rows:
        counts[row["reaction_type"]] = int(row["count"] or 0)

    return JsonResponse(
        {
            "ok": True,
            "current_reaction_type": reaction_type,
            "reactions": [
                {
                    "type": reaction_key,
                    "label": label,
                    "count": counts.get(reaction_key, 0),
                    "is_selected": reaction_key == reaction_type,
                }
                for reaction_key, label in MemberMetricTransactionReaction.REACTION_CHOICES
            ],
        }
    )
