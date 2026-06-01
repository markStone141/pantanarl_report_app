import json
from datetime import timedelta

from django.contrib.auth import login as auth_login, logout as auth_logout
from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Department, Member
from apps.mail.models import MailSendHistory
from apps.mail.services import MailSendError, record_transaction_mail_failure, send_transaction_mail
from apps.targets.models import Period

from .auth import get_member_profile, require_dairymetrics_admin, require_dairymetrics_member
from .forms import (
    DairyMetricsLoginForm,
    DairymetricsV2CloseoutForm,
    DairymetricsV2DepartmentTargetForm,
    DairymetricsV2PersonalSetupForm,
    DairymetricsV2TransactionForm,
    MemberScopeTargetForm,
    MetricAdjustmentForm,
)
from .services.entry_context import (
    build_entry_form,
    build_entry_v2_demo_context,
    build_entry_v2_transaction_demo_context,
    member_departments,
    parse_month_input,
    resolve_metrics_v2_department,
)
from .models import MemberDailyMetricEntry, MemberMetricTransaction, MetricAdjustment
from .services.entry_v2 import (
    build_transaction_mail_preview,
    build_v2_redirect_url,
    get_default_mail_group,
    get_or_create_department_daily_summary,
    transaction_mail_status,
)
from .services.metrics_v2 import build_metrics_v2_dashboard_payload, resolve_metrics_v2_scope
from .selectors import (
    build_admin_daily_overview,
    build_admin_ranking_overview,
    build_admin_month_comparison,
    build_admin_month_overview,
    build_member_daily_overview,
    build_member_month_overview,
    build_member_to_member_comparison,
    build_member_dashboard,
    build_member_ranking_detail,
)


INLINE_ADJUSTMENT_NOTE = "__inline_monthly_adjustment__"
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
ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS = list(range(1000, 5001, 500))
ENTRY_V2_WV_REFUGEE_AMOUNT_OPTIONS = list(range(500, 4001, 500))

def _login_redirect_url(user, *, fallback=""):
    if fallback:
        return fallback
    if user.is_staff:
        return reverse("dairymetrics_admin_overview")
    return reverse("dairymetrics_dashboard")


def _admin_monthly_allowed_fields(department):
    allowed_fields = {
        "approach_count": "number",
        "communication_count": "number",
        "support_amount": "number",
        "location_name": "text",
    }
    if department.code == "WV":
        allowed_fields.update({"cs_count": "number", "refugee_count": "number"})
    else:
        allowed_fields["result_count"] = "number"
    adjustment_fields = {
        "return_postal_count",
        "return_postal_amount",
        "return_qr_count",
        "return_qr_amount",
    }
    for field_name in adjustment_fields:
        allowed_fields[field_name] = "number"
    return allowed_fields, adjustment_fields


def _apply_admin_monthly_update(*, member, department, entry_date, field_name, raw_value):
    allowed_fields, adjustment_fields = _admin_monthly_allowed_fields(department)
    if field_name not in allowed_fields:
        return {"error": "invalid_field"}, 400

    if field_name in adjustment_fields:
        if raw_value == "":
            desired_value = 0
        else:
            try:
                desired_value = int(raw_value)
            except ValueError:
                return {"error": "invalid_value"}, 400
            if desired_value < 0:
                return {"error": "invalid_value"}, 400

        inline_adjustment, _ = MetricAdjustment.objects.get_or_create(
            member=member,
            department=department,
            target_date=entry_date,
            source_type=MetricAdjustment.SOURCE_OTHER,
            note=INLINE_ADJUSTMENT_NOTE,
        )
        other_total = (
            MetricAdjustment.objects.filter(
                member=member,
                department=department,
                target_date=entry_date,
            )
            .exclude(pk=inline_adjustment.pk)
            .aggregate(total=Sum(field_name))
            .get("total")
            or 0
        )
        if desired_value < other_total:
            return {"error": "value_below_existing_adjustments"}, 400
        setattr(inline_adjustment, field_name, desired_value - int(other_total))
        inline_adjustment.save()
        return {"ok": True}, 200

    if allowed_fields[field_name] == "text":
        normalized_value = raw_value
    else:
        if raw_value == "":
            normalized_value = 0
        else:
            try:
                normalized_value = int(raw_value)
            except ValueError:
                return {"error": "invalid_value"}, 400
            if normalized_value < 0:
                return {"error": "invalid_value"}, 400

    entry = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date=entry_date,
    ).first()

    if entry is None:
        if allowed_fields[field_name] == "text" and normalized_value == "":
            return {"ok": True, "skipped": True}, 200
        if allowed_fields[field_name] == "number" and normalized_value == 0:
            return {"ok": True, "skipped": True}, 200
        entry = MemberDailyMetricEntry(
            member=member,
            department=department,
            entry_date=entry_date,
            input_source=MemberDailyMetricEntry.SOURCE_ADMIN,
        )

    if getattr(entry, field_name) == normalized_value:
        return {"ok": True, "skipped": True}, 200

    setattr(entry, field_name, normalized_value)
    if not entry.pk:
        entry.input_source = MemberDailyMetricEntry.SOURCE_ADMIN
    entry.save()
    return {"ok": True}, 200

def _member_directory_queryset():
    return (
        Member.objects.filter(department_links__department__is_active=True)
        .distinct()
        .order_by("name")
        .prefetch_related("department_links__department")
    )


def _build_member_directory():
    members = _member_directory_queryset()
    return [
        {
            "member": member,
            "departments": [link.department for link in member.department_links.all() if link.department.is_active],
        }
        for member in members
    ]


def _member_filter_departments(member_rows):
    departments_by_code = {}
    for row in member_rows:
        for department in row["departments"]:
            departments_by_code[department.code] = department
    return [departments_by_code[code] for code in sorted(departments_by_code)]


def _default_member_filter_code(viewer_member, filter_departments):
    department_codes = [department.code for department in filter_departments]
    if "UN" in department_codes:
        return "UN"
    if viewer_member:
        if viewer_member.default_department and viewer_member.default_department.code in department_codes:
            return viewer_member.default_department.code
        viewer_department = Department.objects.filter(is_active=True, member_links__member=viewer_member).order_by("code").first()
        if viewer_department and viewer_department.code in department_codes:
            return viewer_department.code
    return department_codes[0] if department_codes else ""


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

def _build_member_dashboard_context(*, request, member, readonly=False, viewer_member=None):
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
    selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
    selected_period_id = (request.GET.get("period_id") or "").strip()
    dashboard_data = build_member_dashboard(
        member,
        today=timezone.localdate(),
        department_code=selected_department_code,
        scope=selected_scope,
        start_date=selected_start_date,
        end_date=selected_end_date,
        period_id=selected_period_id or None,
    )
    selected_department = dashboard_data["selected_department"]
    entry_form = None
    scope_target_form = None
    scope_target_form_action = ""
    if not readonly:
        entry_form = build_entry_form(
            member=member,
            department_code=selected_department.code if selected_department else "",
            entry_date=timezone.localdate(),
        )
    if not readonly and selected_department and dashboard_data["selected_card"]:
        selected_card = dashboard_data["selected_card"]
        if selected_card["scope"] in {"period", "month"}:
            scope_target_form = MemberScopeTargetForm(
                member=member,
                scope=selected_card["scope"],
                department=selected_department,
                period=selected_card.get("period_obj"),
                target_month=selected_card.get("month_start"),
            )
            scope_target_form_action = (
                f"{reverse('dairymetrics_scope_target')}?department={selected_department.code}&scope={selected_card['scope']}"
            )
    member_rows = _build_member_directory() if readonly else []
    member_filter_departments = _member_filter_departments(member_rows) if readonly else []
    context = {
        "page_title": "DairyMetrics",
        "member": member,
        "departments": dashboard_data["departments"],
        "selected_department": selected_department,
        "selected_card": dashboard_data["selected_card"],
        "scope_options": dashboard_data["scope_options"],
        "selected_scope": dashboard_data["selected_scope"],
        "entry_form": entry_form,
        "scope_target_form": scope_target_form,
        "scope_target_form_action": scope_target_form_action,
        "is_admin": request.user.is_staff,
        "readonly_dashboard": readonly,
        "viewer_member": viewer_member if readonly else (viewer_member or member),
        "member_rows": member_rows,
        "member_filter_departments": member_filter_departments,
        "member_filter_default_code": _default_member_filter_code(viewer_member, member_filter_departments) if readonly else "",
        "card_base_url": (
            reverse("dairymetrics_member_dashboard", args=[member.id])
            if readonly
            else reverse("dairymetrics_dashboard")
        ),
    }
    if readonly and viewer_member and member and viewer_member.id != member.id and dashboard_data["selected_card"]:
        start_date, end_date = _comparison_scope_bounds(
            dashboard_data["selected_card"],
            today=timezone.localdate(),
        )
        context["member_comparison"] = build_member_to_member_comparison(
            viewer_member,
            member,
            selected_department,
            start_date,
            end_date,
            today_only=dashboard_data["selected_scope"] == "today",
        )
    else:
        context["member_comparison"] = None
    return context


def _resolve_comparison_target_member(request: HttpRequest):
    viewer_member = get_member_profile(request.user)
    target_member = viewer_member
    requested_member_id = (request.GET.get("member") or "").strip()
    if requested_member_id:
        target_member = _member_directory_queryset().filter(pk=requested_member_id).first() or viewer_member
    return viewer_member, target_member


def _comparison_scope_bounds(selected_card, *, today):
    scope = selected_card["scope"]
    if scope == "today":
        return today, today
    if scope == "period" and selected_card.get("period_obj"):
        period = selected_card["period_obj"]
        return period.start_date, min(period.end_date, today)
    if scope == "month":
        return selected_card["month_start"], today
    return selected_card.get("custom_start_date"), selected_card.get("custom_end_date")


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
def dashboard(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    context = _build_member_dashboard_context(request=request, member=member) if member else {
        "page_title": "DairyMetrics",
        "member": None,
        "departments": [],
        "selected_department": None,
        "selected_card": None,
        "entry_form": None,
        "is_admin": request.user.is_staff,
        "readonly_dashboard": False,
        "viewer_member": None,
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest" and member:
        return JsonResponse(
            {
                "card_html": render_to_string(
                    "dairymetrics/partials/dashboard_card.html",
                    context,
                    request=request,
                ),
                "form_html": render_to_string(
                    "dairymetrics/partials/entry_modal_form.html",
                    context,
                    request=request,
                ),
                "target_form_html": render_to_string(
                    "dairymetrics/partials/scope_target_modal_form.html",
                    context,
                    request=request,
                ),
                "department_code": context["selected_department"].code if context["selected_department"] else "",
            }
        )
    return render(request, "dairymetrics/dashboard.html", context)


@require_dairymetrics_member
def member_index(request: HttpRequest) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    member_rows = _build_member_directory()
    selected_member_id = request.GET.get("member")
    selected_member = None
    if selected_member_id:
        selected_member = next((row["member"] for row in member_rows if str(row["member"].id) == selected_member_id), None)
    if not selected_member and member_rows:
        selected_member = member_rows[0]["member"]
    if not selected_member:
        return render(
            request,
            "dairymetrics/dashboard.html",
            {
                "page_title": "DairyMetrics",
                "member": None,
                "viewer_member": viewer_member,
                "departments": [],
                "selected_department": None,
                "selected_card": None,
                "scope_options": [],
                "selected_scope": "today",
                "entry_form": None,
                "scope_target_form": None,
                "scope_target_form_action": "",
                "is_admin": request.user.is_staff,
                "readonly_dashboard": True,
                "member_rows": [],
                "member_filter_departments": [],
                "member_filter_default_code": "",
            },
        )
    return member_dashboard(request, selected_member.id)


@require_dairymetrics_member
def member_dashboard(request: HttpRequest, member_id: int) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    target_member = get_object_or_404(_member_directory_queryset(), pk=member_id)
    context = _build_member_dashboard_context(
        request=request,
        member=target_member,
        readonly=True,
        viewer_member=viewer_member,
    )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "card_html": render_to_string(
                    "dairymetrics/partials/dashboard_card.html",
                    context,
                    request=request,
                ),
                "form_html": "",
                "target_form_html": "",
                "department_code": context["selected_department"].code if context["selected_department"] else "",
                "page_subtitle": f"{viewer_member.name}さんでログイン中" if viewer_member else "管理者としてメンバーデータを閲覧中",
                "viewed_member_name": target_member.name,
            }
        )
    return render(request, "dairymetrics/dashboard.html", context)


@require_dairymetrics_member
def comparison_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff:
        return redirect("dairymetrics_admin_overview")
    viewer_member, target_member = _resolve_comparison_target_member(request)
    if target_member:
        selected_department_code = (request.GET.get("department") or "").strip()
        selected_scope = (request.GET.get("scope") or "today").strip()
        selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
        selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
        selected_period_id = (request.GET.get("period_id") or "").strip()
        dashboard_data = build_member_dashboard(
            target_member,
            today=timezone.localdate(),
            department_code=selected_department_code,
            scope=selected_scope,
            start_date=selected_start_date,
            end_date=selected_end_date,
            period_id=selected_period_id or None,
        )
        context = {
            "page_title": "DairyMetrics",
            "member": target_member,
            "viewer_member": viewer_member,
            "departments": dashboard_data["departments"],
            "selected_department": dashboard_data["selected_department"],
            "selected_card": dashboard_data["selected_card"],
            "scope_options": dashboard_data["scope_options"],
            "selected_scope": dashboard_data["selected_scope"],
            "is_admin": request.user.is_staff,
            "comparison_member_id": (
                str(target_member.id) if viewer_member and target_member.id != viewer_member.id else ""
            ),
            "return_dashboard_url": (
                reverse("dairymetrics_member_dashboard", args=[target_member.id])
                if viewer_member and target_member.id != viewer_member.id
                else reverse("dairymetrics_dashboard")
            )
        }
        if viewer_member and target_member.id != viewer_member.id and dashboard_data["selected_card"]:
            start_date, end_date = _comparison_scope_bounds(
                dashboard_data["selected_card"],
                today=timezone.localdate(),
            )
            context["member_comparison"] = build_member_to_member_comparison(
                viewer_member,
                target_member,
                dashboard_data["selected_department"],
                start_date,
                end_date,
                today_only=dashboard_data["selected_scope"] == "today",
            )
        else:
            context["member_comparison"] = None
    else:
        context = {
        "page_title": "DairyMetrics",
        "member": None,
        "viewer_member": None,
        "departments": [],
        "selected_department": None,
        "selected_card": None,
        "scope_options": [],
        "selected_scope": "today",
        "entry_form": None,
        "is_admin": request.user.is_staff,
        "comparison_member_id": "",
        "return_dashboard_url": reverse("dairymetrics_dashboard"),
        "member_comparison": None,
    }
    return render(request, "dairymetrics/comparison.html", context)


@require_dairymetrics_member
def member_overview(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    selected_department_code = (request.GET.get("department") or "").strip()
    overview = build_member_daily_overview(
        member,
        department_code=selected_department_code,
        today=timezone.localdate(),
    )
    context = {
        "member": member,
        "is_admin": request.user.is_staff,
        "today": overview["today"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "submission_summary": overview["submission_summary"],
        "today_department_totals": overview["today_department_totals"],
        "activity_cards": overview["activity_cards"],
    }
    return render(request, "dairymetrics/member_overview.html", context)


@require_dairymetrics_member
def member_monthly_overview(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    target_month = parse_date(f"{(request.GET.get('month') or timezone.localdate().strftime('%Y-%m'))}-01")
    if not target_month:
        target_month = timezone.localdate().replace(day=1)
    selected_department_code = (request.GET.get("department") or "").strip()
    active_tab = (request.GET.get("tab") or "field").strip()
    if active_tab not in {"field", "adjustment"}:
        active_tab = "field"

    overview = build_member_month_overview(
        member,
        target_month=target_month,
        department_code=selected_department_code,
        today=timezone.localdate(),
    )
    context = {
        "member": member,
        "is_admin": request.user.is_staff,
        "target_month": target_month,
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "month_days": overview["month_days"],
        "rows": overview["field_rows"] if active_tab == "field" else overview["adjustment_rows"],
        "active_tab": active_tab,
    }
    return render(request, "dairymetrics/member_monthly.html", context)


@require_dairymetrics_member
def comparison_ranking_detail(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff:
        return JsonResponse({"error": "admin_not_supported"}, status=404)
    viewer_member, target_member = _resolve_comparison_target_member(request)
    if not target_member:
        return JsonResponse({"error": "member_not_found"}, status=404)

    metric_key = (request.GET.get("metric") or "").strip()
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
    selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
    selected_period_id = (request.GET.get("period_id") or "").strip()
    detail = build_member_ranking_detail(
        target_member,
        today=timezone.localdate(),
        department_code=selected_department_code,
        scope=selected_scope,
        start_date=selected_start_date,
        end_date=selected_end_date,
        period_id=selected_period_id or None,
        metric_key=metric_key,
    )
    if not detail:
        return JsonResponse({"error": "metric_not_found"}, status=404)

    return JsonResponse(
        {
            "modal_html": render_to_string(
                "dairymetrics/partials/ranking_detail_modal.html",
                detail,
                request=request,
            ),
        }
    )


@require_dairymetrics_admin
def admin_ranking_overview(request: HttpRequest) -> HttpResponse:
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
    selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
    overview = build_admin_ranking_overview(
        department_code=selected_department_code,
        scope=selected_scope,
        start_date=selected_start_date,
        end_date=selected_end_date,
        today=timezone.localdate(),
    )
    context = {
        "today": overview["today"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "ranking_metrics": overview["ranking_metrics"],
        "scope_options": overview["scope_options"],
        "selected_scope": overview["selected_scope"],
        "scope_summary": overview["scope_summary"],
        "custom_start_date": overview["custom_start_date"],
        "custom_end_date": overview["custom_end_date"],
    }
    return render(request, "dairymetrics/admin_ranking.html", context)


@require_dairymetrics_member
def scope_target_form(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    scope = (request.GET.get("scope") or "").strip()
    department_code = (request.GET.get("department") or "").strip()
    department = Department.objects.filter(
        is_active=True,
        code=department_code,
        member_links__member=member,
    ).first()
    if scope not in {"period", "month"} or not department:
        return redirect("dairymetrics_dashboard")

    today = timezone.localdate()
    selected_card = build_member_dashboard(
        member,
        today=today,
        department_code=department.code,
        scope=scope,
    )["selected_card"]
    if not selected_card or selected_card["scope"] != scope:
        return redirect("dairymetrics_dashboard")
    form = MemberScopeTargetForm(
        request.POST or None,
        member=member,
        scope=scope,
        department=department,
        period=selected_card.get("period_obj"),
        target_month=selected_card.get("month_start"),
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(f"{reverse('dairymetrics_dashboard')}?department={department.code}&scope={scope}&saved=1")
    return render(
        request,
        "dairymetrics/scope_target_form.html",
        {
            "form": form,
            "scope_target_form": form,
            "scope_target_form_action": f"{reverse('dairymetrics_scope_target')}?department={department.code}&scope={scope}",
            "scope": scope,
            "department": department,
        },
    )


@require_dairymetrics_member
def entry_form(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    initial_date = parse_date((request.GET.get("date") or "").strip()) or timezone.localdate()
    selected_department = (request.GET.get("department") or "").strip()
    form = build_entry_form(
        member=member,
        data=request.POST or None,
        department_code=selected_department,
        entry_date=initial_date,
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        existing = MemberDailyMetricEntry.objects.filter(
            member=member,
            department=saved.department,
            entry_date=saved.entry_date,
        ).first()
        if existing and saved.pk is None:
            saved.pk = existing.pk
            saved.created_at = existing.created_at
        saved.member = member
        saved.input_source = MemberDailyMetricEntry.SOURCE_MEMBER
        submit_action = (request.POST.get("submit_action") or "save").strip()
        is_closing = submit_action == "close_activity"
        saved.activity_closed = is_closing
        saved.activity_closed_at = timezone.now() if is_closing else None
        saved.save()
        return redirect(f"{reverse('dairymetrics_dashboard')}?saved=1")

    departments = member_departments(member)
    context = {
        "form": form,
        "member": member,
        "departments": departments,
        "selected_department_code": selected_department,
    }
    return render(request, "dairymetrics/entry_form.html", context)


@require_dairymetrics_member
def entry_form_v2_demo(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    entry_date = parse_date((request.GET.get("date") or "").strip()) or timezone.localdate()
    selected_department = (request.GET.get("department") or "").strip()
    context = build_entry_v2_demo_context(
        member=member,
        selected_department=selected_department,
        entry_date=entry_date,
        age_bands=ENTRY_V2_AGE_BANDS,
        gender_bands=ENTRY_V2_GENDER_BANDS,
        nationality_bands=ENTRY_V2_NATIONALITY_BANDS,
    )
    return render(request, "dairymetrics/entry_form_v2.html", context)


@require_dairymetrics_member
def metrics_v2_demo(request: HttpRequest) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    departments, selected_department = resolve_metrics_v2_department(request=request, member=viewer_member)
    if not selected_department:
        return redirect("dairymetrics_dashboard")
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
    requested_period = None
    raw_period_id = (request.GET.get("period_id") or "").strip()
    if raw_period_id.isdigit():
        requested_period = Period.objects.filter(pk=int(raw_period_id)).first()
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
    available_periods = list(Period.objects.order_by("-end_date", "-start_date", "-id")[:18])

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
    form_initial = {
        "department": selected_department_obj,
        "entry_date": entry_date,
        "location_name": (request.GET.get("location_name") or "").strip(),
        "daily_target_count": (request.GET.get("daily_target_count") or "").strip() or 0,
        "daily_target_cs_count": (request.GET.get("daily_target_cs_count") or "").strip() or 0,
        "daily_target_refugee_count": (request.GET.get("daily_target_refugee_count") or "").strip() or 0,
        "daily_target_amount": (request.GET.get("daily_target_amount") or "").strip() or 0,
    }
    personal_setup_form = DairymetricsV2PersonalSetupForm(member=member, initial=form_initial)
    context = build_entry_v2_transaction_demo_context(
        member=member,
        selected_department=selected_department_code,
        entry_date=entry_date,
        personal_setup_form=personal_setup_form,
        age_bands=ENTRY_V2_AGE_BANDS,
        gender_bands=ENTRY_V2_GENDER_BANDS,
        nationality_bands=ENTRY_V2_NATIONALITY_BANDS,
        target_count_options=ENTRY_V2_TARGET_COUNT_OPTIONS,
        target_amount_options=ENTRY_V2_TARGET_AMOUNT_OPTIONS,
        transaction_amount_options=ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS,
        wv_refugee_amount_options=ENTRY_V2_WV_REFUGEE_AMOUNT_OPTIONS,
    )
    return JsonResponse(
        {
            "setup_html": _render_personal_setup_form_partial(request, context, inline=False),
            "inline_html": _render_personal_setup_form_partial(request, context, inline=True),
            "is_wv": context["selected_department_is_wv"],
        }
    )


@require_dairymetrics_member
def entry_form_v2_transaction_demo(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

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
        elif action in {"send_transaction_mock", "send_transaction_mail"}:
            preview_tx_id = (request.POST.get("preview_transaction_id") or "").strip()
            preview_history_id = (request.POST.get("preview_history_id") or "").strip()
            edited_subject = (request.POST.get("preview_subject") or "").strip()
            edited_body = (request.POST.get("preview_body") or "").strip()
            if not selected_department_obj:
                status_message = "送信対象の決済を確認してください。"
            else:
                preview_transaction = None
                if preview_tx_id.isdigit():
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
        transaction_amount_options=ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS,
        wv_refugee_amount_options=ENTRY_V2_WV_REFUGEE_AMOUNT_OPTIONS,
    )
    return render(request, "dairymetrics/entry_form_v2_transaction.html", context)


@require_dairymetrics_admin
def admin_overview(request: HttpRequest) -> HttpResponse:
    selected_department_code = (request.GET.get("department") or "").strip()
    overview = build_admin_daily_overview(
        department_code=selected_department_code,
        today=timezone.localdate(),
    )
    context = {
        "today": overview["today"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "submission_summary": overview["submission_summary"],
        "today_department_totals": overview["today_department_totals"],
        "activity_cards": overview["activity_cards"],
        "ranking_metrics": overview["ranking_metrics"],
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "overview_html": render_to_string(
                    "dairymetrics/partials/admin_overview_content.html",
                    context,
                    request=request,
                ),
                "department_code": context["selected_department"].code if context["selected_department"] else "",
            }
        )
    return render(request, "dairymetrics/admin_overview.html", context)


@require_dairymetrics_admin
def admin_monthly_overview(request: HttpRequest) -> HttpResponse:
    target_month = parse_date(f"{(request.GET.get('month') or timezone.localdate().strftime('%Y-%m'))}-01")
    if not target_month:
        target_month = timezone.localdate().replace(day=1)
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_sort = (request.GET.get("sort") or "activity_days").strip()
    if selected_sort not in {"activity_days", "amount", "approach", "count"}:
        selected_sort = "activity_days"
    active_tab = (request.GET.get("tab") or "field").strip()
    if active_tab not in {"field", "adjustment"}:
        active_tab = "field"
    overview = build_admin_month_overview(
        target_month=target_month,
        department_code=selected_department_code,
        sort_key=selected_sort,
        today=timezone.localdate(),
    )
    context = {
        "target_month": target_month,
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "month_days": overview["month_days"],
        "rows": overview["field_rows"] if active_tab == "field" else overview["adjustment_rows"],
        "active_tab": active_tab,
        "selected_sort": overview["selected_sort"],
        "sort_options": overview["sort_options"],
        "activity_summary": overview["activity_summary"],
    }
    return render(request, "dairymetrics/admin_monthly.html", context)


@require_dairymetrics_admin
def admin_monthly_update_cell(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    member_id = request.POST.get("member_id")
    department_code = (request.POST.get("department") or "").strip()
    entry_date = parse_date((request.POST.get("entry_date") or "").strip())
    field_name = (request.POST.get("field") or "").strip()
    raw_value = (request.POST.get("value") or "").strip()

    if not member_id or not department_code or not entry_date or not field_name:
        return JsonResponse({"error": "invalid_request"}, status=400)

    department = get_object_or_404(Department.objects.filter(is_active=True), code=department_code)
    member = get_object_or_404(
        Member.objects.filter(department_links__department=department).distinct(),
        pk=member_id,
    )
    payload, status = _apply_admin_monthly_update(
        member=member,
        department=department,
        entry_date=entry_date,
        field_name=field_name,
        raw_value=raw_value,
    )
    return JsonResponse(payload, status=status)


@require_dairymetrics_admin
def admin_monthly_bulk_update(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    changes = payload.get("changes")
    if not isinstance(changes, list):
        return JsonResponse({"error": "invalid_request"}, status=400)
    if not changes:
        return JsonResponse({"ok": True, "updated_count": 0})

    with transaction.atomic():
        for index, change in enumerate(changes):
            member_id = str(change.get("member_id") or "").strip()
            department_code = str(change.get("department") or "").strip()
            entry_date = parse_date(str(change.get("entry_date") or "").strip())
            field_name = str(change.get("field") or "").strip()
            raw_value = str(change.get("value") or "").strip()

            if not member_id or not department_code or not entry_date or not field_name:
                return JsonResponse({"error": "invalid_request", "index": index}, status=400)

            department = get_object_or_404(Department.objects.filter(is_active=True), code=department_code)
            member = get_object_or_404(
                Member.objects.filter(department_links__department=department).distinct(),
                pk=member_id,
            )
            result, status = _apply_admin_monthly_update(
                member=member,
                department=department,
                entry_date=entry_date,
                field_name=field_name,
                raw_value=raw_value,
            )
            if status != 200:
                result["index"] = index
                return JsonResponse(result, status=status)

    return JsonResponse({"ok": True, "updated_count": len(changes)})


@require_dairymetrics_admin
def admin_monthly_comparison(request: HttpRequest) -> HttpResponse:
    target_month = parse_date(f"{(request.GET.get('month') or timezone.localdate().strftime('%Y-%m'))}-01")
    if not target_month:
        target_month = timezone.localdate().replace(day=1)
    compare_month = parse_date((request.GET.get("compare_month") or ""))
    if compare_month:
        compare_month = compare_month.replace(day=1)
    else:
        previous_month_end = target_month.replace(day=1) - timedelta(days=1)
        compare_month = previous_month_end.replace(day=1)
    selected_department_code = (request.GET.get("department") or "").strip()
    overview = build_admin_month_comparison(
        target_month=target_month,
        compare_month=compare_month,
        department_code=selected_department_code,
    )
    context = {
        "target_month": overview["target_month"],
        "compare_month": overview["compare_month"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "rows": overview["rows"],
        "monthly_department_totals": overview["monthly_department_totals"],
    }
    return render(request, "dairymetrics/admin_monthly_comparison.html", context)


@require_dairymetrics_admin
def adjustment_create(request: HttpRequest) -> HttpResponse:
    form = MetricAdjustmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        adjustment = form.save(commit=False)
        adjustment.created_by = request.user
        adjustment.save()
        return redirect(f"{reverse('dairymetrics_admin_monthly_overview')}?month={adjustment.target_date.strftime('%Y-%m')}")

    recent_adjustments = MetricAdjustment.objects.select_related("member", "department", "created_by")[:10]
    return render(
        request,
        "dairymetrics/admin_adjustment_form.html",
        {"form": form, "recent_adjustments": recent_adjustments},
    )
