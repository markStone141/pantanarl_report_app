from django.contrib.auth import login as auth_login, logout as auth_logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Department

from .auth import get_member_profile, require_dairymetrics_admin, require_dairymetrics_member
from .forms import DairyMetricsLoginForm, MemberDailyMetricEntryForm, MetricAdjustmentForm
from .models import MemberDailyMetricEntry, MetricAdjustment
from .selectors import build_admin_month_overview, build_member_dashboard


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
    context = {
        "page_title": "DairyMetrics",
        "member": member,
        "dashboard_cards": build_member_dashboard(member, today=timezone.localdate()) if member else [],
        "is_admin": request.user.is_staff,
    }
    return render(request, "dairymetrics/dashboard.html", context)


@require_dairymetrics_member
def entry_form(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    initial_date = parse_date((request.GET.get("date") or "").strip()) or timezone.localdate()
    selected_department = (request.GET.get("department") or "").strip()
    instance = None
    if selected_department:
        instance = MemberDailyMetricEntry.objects.filter(
            member=member,
            department__code=selected_department,
            entry_date=initial_date,
        ).select_related("department").first()

    form = MemberDailyMetricEntryForm(request.POST or None, instance=instance, member=member, initial={"entry_date": initial_date})
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
        saved.save()
        return redirect(f"{reverse('dairymetrics_dashboard')}?saved=1")

    departments = Department.objects.filter(is_active=True, member_links__member=member).distinct().order_by("code")
    context = {
        "form": form,
        "member": member,
        "departments": departments,
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
