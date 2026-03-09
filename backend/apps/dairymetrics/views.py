from django.contrib.auth import login as auth_login, logout as auth_logout
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Department, Member

from .auth import get_member_profile, require_dairymetrics_admin, require_dairymetrics_member
from .forms import DairyMetricsLoginForm, MemberDailyMetricEntryForm, MemberScopeTargetForm, MetricAdjustmentForm
from .models import MemberDailyMetricEntry, MetricAdjustment
from .selectors import build_admin_month_overview, build_member_dashboard


def _build_entry_form(*, member, data=None, department_code="", entry_date=None):
    entry_date = entry_date or timezone.localdate()
    instance = None
    if department_code:
        instance = MemberDailyMetricEntry.objects.filter(
            member=member,
            department__code=department_code,
            entry_date=entry_date,
        ).select_related("department").first()
    initial = {"entry_date": entry_date}
    if department_code and not instance:
        department = Department.objects.filter(
            is_active=True,
            code=department_code,
            member_links__member=member,
        ).first()
        if department:
            initial["department"] = department
    return MemberDailyMetricEntryForm(
        data=data,
        instance=instance,
        member=member,
        initial=initial,
    )

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


def _build_member_filter_departments(member_rows):
    departments = {}
    for row in member_rows:
        for department in row["departments"]:
            departments[department.code] = department
    return [departments[code] for code in sorted(departments)]


def _build_member_dashboard_context(*, request, member, readonly=False, viewer_member=None):
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
    selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
    dashboard_data = build_member_dashboard(
        member,
        today=timezone.localdate(),
        department_code=selected_department_code,
        scope=selected_scope,
        start_date=selected_start_date,
        end_date=selected_end_date,
    )
    selected_department = dashboard_data["selected_department"]
    entry_form = None
    scope_target_form = None
    scope_target_form_action = ""
    if not readonly:
        entry_form = _build_entry_form(
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
    return {
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
        "viewer_member": viewer_member or member,
        "member_rows": member_rows,
        "member_filter_departments": _build_member_filter_departments(member_rows) if readonly else [],
    }


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dairymetrics_dashboard")

    form = DairyMetricsLoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.user)
        return redirect(request.POST.get("next") or reverse("dairymetrics_dashboard"))
    return render(request, "dairymetrics/login.html", {"form": form, "next": request.GET.get("next", "")})


def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    return redirect("dairymetrics_login")


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
                "page_subtitle": f"{viewer_member.name}さんでログイン中" if viewer_member else "他メンバーデータ",
                "viewed_member_name": target_member.name,
            }
        )
    return render(request, "dairymetrics/dashboard.html", context)


@require_dairymetrics_member
def comparison_view(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    context = _build_member_dashboard_context(request=request, member=member) if member else {
        "page_title": "DairyMetrics",
        "member": None,
        "departments": [],
        "selected_department": None,
        "selected_card": None,
        "entry_form": None,
        "is_admin": request.user.is_staff,
    }
    return render(request, "dairymetrics/comparison.html", context)


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
    form = _build_entry_form(
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
        submit_action = (request.POST.get("submit_action") or "save").strip()
        is_closing = submit_action == "close_activity"
        saved.activity_closed = is_closing
        saved.activity_closed_at = timezone.now() if is_closing else None
        saved.save()
        return redirect(f"{reverse('dairymetrics_dashboard')}?saved=1")

    departments = Department.objects.filter(is_active=True, member_links__member=member).distinct().order_by("code")
    context = {
        "form": form,
        "member": member,
        "departments": departments,
        "selected_department_code": selected_department,
    }
    return render(request, "dairymetrics/entry_form.html", context)


@require_dairymetrics_admin
def admin_overview(request: HttpRequest) -> HttpResponse:
    target_month = parse_date(f"{(request.GET.get('month') or timezone.localdate().strftime('%Y-%m'))}-01")
    if not target_month:
        target_month = timezone.localdate().replace(day=1)
    context = {
        "target_month": target_month,
        "rows": build_admin_month_overview(target_month=target_month),
    }
    return render(request, "dairymetrics/admin_overview.html", context)


@require_dairymetrics_admin
def adjustment_create(request: HttpRequest) -> HttpResponse:
    form = MetricAdjustmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        adjustment = form.save(commit=False)
        adjustment.created_by = request.user
        adjustment.save()
        return redirect(f"{reverse('dairymetrics_admin_overview')}?month={adjustment.target_date.strftime('%Y-%m')}")

    recent_adjustments = MetricAdjustment.objects.select_related("member", "department", "created_by")[:10]
    return render(
        request,
        "dairymetrics/admin_adjustment_form.html",
        {"form": form, "recent_adjustments": recent_adjustments},
    )
