from django.contrib.auth import login as auth_login, logout as auth_logout
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Department

from .auth import get_member_profile, require_dairymetrics_admin, require_dairymetrics_member
from .forms import DairyMetricsLoginForm, MemberDailyMetricEntryForm, MetricAdjustmentForm
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


def _build_member_dashboard_context(*, request, member):
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    dashboard_data = build_member_dashboard(
        member,
        today=timezone.localdate(),
        department_code=selected_department_code,
        scope=selected_scope,
    )
    selected_department = dashboard_data["selected_department"]
    entry_form = _build_entry_form(
        member=member,
        department_code=selected_department.code if selected_department else "",
        entry_date=timezone.localdate(),
    )
    return {
        "page_title": "DairyMetrics",
        "member": member,
        "departments": dashboard_data["departments"],
        "selected_department": selected_department,
        "selected_card": dashboard_data["selected_card"],
        "scope_options": dashboard_data["scope_options"],
        "selected_scope": dashboard_data["selected_scope"],
        "entry_form": entry_form,
        "is_admin": request.user.is_staff,
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
                "department_code": context["selected_department"].code if context["selected_department"] else "",
            }
        )
    return render(request, "dairymetrics/dashboard.html", context)


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
