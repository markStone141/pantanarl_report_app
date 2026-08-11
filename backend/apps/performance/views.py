from functools import wraps
from datetime import date

from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlencode
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, resolve_request_role
from apps.accounts.models import Department, Member, MemberDepartment
from apps.common.target_periods import period_options_active_first
from apps.dairymetrics.forms import DairyMetricsLoginForm, DairymetricsV2TransactionForm, MemberScopeTargetForm
from apps.dairymetrics.models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MetricAdjustment,
    WVMetricCancellation,
)
from apps.dairymetrics.services.activity_state import auto_close_stale_entries
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_department_final_actual_totals_by_codes,
    collect_member_final_actual_totals_by_ids,
)
from apps.performance.services.progress import (
    collect_adjustment_amounts_by_codes,
    month_end,
)
from apps.performance.services.formatters import (
    amount_text as _amount_text,
    count_text as _count_text,
    field_amount_text as _field_amount_text,
    field_count_text as _field_count_text,
    final_amount_text as _final_amount_text,
    final_count_subtext as _final_count_subtext,
    final_count_text as _final_count_text,
    final_count_value as _final_count_value,
    wv_count_detail_text as _wv_count_detail_text,
)
from apps.performance.services.member_details import (
    attach_transaction_edit_urls,
    build_member_dashboard_entry_rows,
    build_trend_date_links,
)
from apps.performance.services.navigation import (
    can_edit_member_performance,
    performance_member_nav_items,
    performance_member_page_nav_links,
    performance_nav_items,
    performance_next_url,
    performance_redirect_for_user,
)
from apps.performance.services.scopes import (
    period_display_label as _period_display_label,
    period_range_label as _period_range_label,
    resolve_current_period as _resolve_current_period,
    resolve_history_period_from_request as _resolve_history_period_from_request,
    resolve_performance_history_scope as _resolve_performance_history_scope,
)
from apps.performance.services.admin_entries import build_admin_entry_management_page
from apps.performance.services.adjustments import (
    combined_adjustment_list_rows,
    filtered_adjustments_queryset,
)
from apps.performance.services.closeout_notes import resolve_closeout_notes_scope
from apps.performance.services.dashboard_snapshots import (
    build_performance_dashboard_snapshot,
    build_performance_history_snapshot,
)
from apps.performance.services.member_ajax import (
    build_member_dashboard_detail_context,
    build_member_history_day_detail_context,
    build_member_history_list_context,
    build_member_recent_detail_context,
)
from apps.performance.services.member_cards import resolve_member_card_department
from apps.performance.services.member_pages import (
    build_member_dashboard_context,
    build_member_history_context,
)
from apps.performance.services.past_entries import (
    create_past_entry_with_transactions,
    normalize_transaction_payloads,
    parse_transactions_payload,
    transaction_preview_rows,
)
from apps.performance.services.trends import (
    EMPTY_ADJUSTMENT_TOTALS,
    build_adjustment_totals_map,
    build_overall_activity_trend,
    entry_final_count_value,
)
from apps.performance.services.today_details import build_department_today_detail_context
from .forms import (
    PerformanceAdminEntryFilterForm,
    PerformanceAdjustmentListFilterForm,
    PerformanceEntryFilterForm,
    PerformancePastEntryCreateForm,
    PerformancePastEntrySelectionForm,
    PerformanceMemberDailyMetricEntryForm,
    PerformanceMetricAdjustmentForm,
)

User = get_user_model()

def require_performance_roles(*allowed_roles: str, auto_close: bool = True):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            role = resolve_request_role(request)
            if role not in allowed_roles:
                next_url = request.get_full_path()
                query = urlencode({"next": next_url}) if next_url else ""
                login_url = reverse("performance_login")
                return redirect(f"{login_url}?{query}" if query else login_url)
            if auto_close:
                auto_close_stale_entries()
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator

def _resolve_performance_member_department_or_404(*, member, department_id):
    department = get_object_or_404(Department, pk=department_id, is_active=True)
    if not MemberDepartment.objects.filter(member=member, department=department).exists() and member.default_department_id != department.id:
        raise Http404
    return department

def performance_login(request: HttpRequest) -> HttpResponse:
    role = resolve_request_role(request)
    if role in {ROLE_ADMIN, ROLE_REPORT} and request.user.is_authenticated:
        return performance_redirect_for_user(request.user, fallback=request.GET.get("next", ""))

    form = DairyMetricsLoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.user)
        return performance_redirect_for_user(form.user, fallback=request.POST.get("next", ""))

    return render(
        request,
        "performance/login.html",
        {
            "form": form,
            "next": request.GET.get("next", ""),
        },
    )

def performance_logout(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    return redirect("performance_login")

def _filtered_entries_queryset(cleaned_data):
    queryset = MemberDailyMetricEntry.objects.select_related("member", "department").order_by("-entry_date", "department__code", "member__name")
    department = cleaned_data.get("department")
    member = cleaned_data.get("member")
    date_from = cleaned_data.get("date_from")
    date_to = cleaned_data.get("date_to")
    if department:
        queryset = queryset.filter(department=department)
    if member:
        queryset = queryset.filter(member=member)
    if date_from:
        queryset = queryset.filter(entry_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(entry_date__lte=date_to)
    return queryset

def _resolve_default_dashboard_department():
    return (
        Department.objects.filter(is_active=True, code="UN").first()
        or Department.objects.filter(is_active=True).order_by("code", "id").first()
    )

def _resolve_default_dashboard_department_for_request(request: HttpRequest):
    if resolve_request_role(request) == ROLE_REPORT:
        member = getattr(request.user, "member_profile", None)
        if member is not None:
            if member.default_department_id:
                department = Department.objects.filter(pk=member.default_department_id, is_active=True).first()
                if department is not None:
                    return department
            department = (
                Department.objects.filter(member_links__member=member, is_active=True)
                .order_by("code", "id")
                .first()
            )
            if department is not None:
                return department
    return _resolve_default_dashboard_department()

def _parse_selected_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None

def _parse_selected_month(value, *, default):
    if not value:
        return default.replace(day=1)
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        return default.replace(day=1)


@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_index(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    department_id = request.GET.get("dashboard_department")
    dashboard_department = None
    if department_id:
        dashboard_department = Department.objects.filter(pk=department_id, is_active=True).first()
    if dashboard_department is None:
        dashboard_department = _resolve_default_dashboard_department_for_request(request)
    dashboard_month = today.replace(day=1)
    dashboard_period = _resolve_current_period(today)
    dashboard_start = request.GET.get("dashboard_start") or ""
    dashboard_end = request.GET.get("dashboard_end") or ""
    dashboard_snapshot = build_performance_dashboard_snapshot(
        department=dashboard_department,
        target_month=dashboard_month,
        period=dashboard_period,
    )
    nav_items = performance_nav_items()
    if resolve_request_role(request) == ROLE_REPORT:
        nav_items = performance_member_nav_items(is_admin=False)
    context = {
        "nav_items": nav_items,
        "dashboard_snapshot": dashboard_snapshot,
        "dashboard_departments": Department.objects.filter(is_active=True).order_by("code", "id"),
        "dashboard_department": dashboard_department,
        "dashboard_month": dashboard_month,
        "dashboard_period": dashboard_period,
        "dashboard_periods": period_options_active_first(target_date=today),
        "dashboard_scope": "month",
        "dashboard_start": dashboard_start,
        "dashboard_end": dashboard_end,
        "status_message": request.GET.get("status") or "",
        **build_department_today_detail_context(
            department=dashboard_department,
            target_date=today,
            next_url=request.get_full_path(),
        ),
    }
    return render(request, "performance/index.html", context)

@require_performance_roles(ROLE_ADMIN)
def performance_admin_entries(request: HttpRequest) -> HttpResponse:
    filter_data = request.GET.copy()
    if not filter_data:
        filter_data["date_from"] = ""
        filter_data["date_to"] = ""
    filter_form = PerformanceAdminEntryFilterForm(filter_data)
    page_obj = None
    paginator = None
    summary_rows = []
    current_query = request.GET.copy()
    current_query.pop("page", None)
    if filter_form.is_valid():
        payload = build_admin_entry_management_page(
            cleaned_data=filter_form.cleaned_data,
            page_number=request.GET.get("page") or 1,
            next_url=request.get_full_path(),
        )
        paginator = payload["paginator"]
        page_obj = payload["page_obj"]
        summary_rows = payload["summary_rows"]
    context = {
        "nav_items": performance_nav_items(),
        "filter_form": filter_form,
        "page_obj": page_obj,
        "paginator": paginator,
        "summary_rows": summary_rows,
        "current_query_string": current_query.urlencode(),
    }
    return render(request, "performance/admin_entries.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT, auto_close=False)
def performance_closeout_notes(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    notes_scope = resolve_closeout_notes_scope(request.GET, today=today)
    selected_department = (request.GET.get("department") or "").strip()
    selected_member = (request.GET.get("member") or "").strip()
    query = (request.GET.get("q") or "").strip()

    entries = (
        MemberDailyMetricEntry.objects.filter(
            entry_date__range=(notes_scope.start_date, notes_scope.end_date),
        )
        .exclude(memo="")
        .select_related("member", "department")
        .order_by("-entry_date", "member__name", "department__code", "-id")
    )
    if selected_department.isdigit():
        entries = entries.filter(department_id=int(selected_department))
    if selected_member.isdigit():
        entries = entries.filter(member_id=int(selected_member))
    if query:
        entries = entries.filter(
            Q(memo__icontains=query)
            | Q(member__name__icontains=query)
            | Q(department__code__icontains=query)
            | Q(location_name__icontains=query)
        )

    paginator = Paginator(entries, 30)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    nav_items = performance_nav_items()
    if resolve_request_role(request) == ROLE_REPORT:
        nav_items = performance_member_nav_items(is_admin=False)
    pagination_query = request.GET.copy()
    pagination_query.pop("page", None)
    context = {
        "nav_items": nav_items,
        "page_obj": page_obj,
        "entries": page_obj.object_list,
        "selected_department": selected_department,
        "selected_member": selected_member,
        "query": query,
        "date_from": notes_scope.start_date,
        "date_to": notes_scope.end_date,
        "today": today,
        "notes_scope": notes_scope,
        "selected_month": (request.GET.get("month") or "").strip(),
        "selected_period_id": (request.GET.get("period_id") or "").strip(),
        "pagination_query": pagination_query.urlencode(),
    }
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "results_html": render_to_string(
                    "performance/partials/closeout_note_results.html",
                    context,
                    request=request,
                ),
                "count": paginator.count,
                "scope_key": notes_scope.key,
                "scope_label": notes_scope.label,
            }
        )
    context.update(
        {
            "departments": Department.objects.filter(is_active=True).order_by("code", "id"),
            "members": Member.objects.order_by("name", "id"),
            "period_options": period_options_active_first(target_date=today),
        }
    )
    return render(request, "performance/closeout_notes.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_history(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    dashboard_scope = request.GET.get("dashboard_scope") or "month"
    if dashboard_scope not in {"month", "period", "range"}:
        dashboard_scope = "month"
    department_id = request.GET.get("dashboard_department")
    dashboard_department = None
    if department_id:
        dashboard_department = Department.objects.filter(pk=department_id, is_active=True).first()
    if dashboard_department is None:
        dashboard_department = _resolve_default_dashboard_department_for_request(request)
    dashboard_month = _parse_selected_month(request.GET.get("dashboard_month"), default=today)
    dashboard_period = _resolve_history_period_from_request(request, today=today, scope_value=dashboard_scope)
    dashboard_start = request.GET.get("dashboard_start") or ""
    dashboard_end = request.GET.get("dashboard_end") or ""
    scope = _resolve_performance_history_scope(
        today=today,
        scope_value=dashboard_scope,
        requested_month=dashboard_month,
        requested_period=dashboard_period,
        requested_start=_parse_selected_date(dashboard_start),
        requested_end=_parse_selected_date(dashboard_end),
    )
    history_snapshot = build_performance_history_snapshot(
        department=dashboard_department,
        scope=scope,
    )
    nav_items = performance_nav_items()
    if resolve_request_role(request) == ROLE_REPORT:
        nav_items = performance_member_nav_items(is_admin=False)
    context = {
        "nav_items": nav_items,
        "dashboard_departments": Department.objects.filter(is_active=True).order_by("code", "id"),
        "dashboard_department": dashboard_department,
        "dashboard_month": dashboard_month,
        "dashboard_period": dashboard_period,
        "dashboard_periods": period_options_active_first(target_date=today),
        "dashboard_scope": dashboard_scope,
        "dashboard_start": dashboard_start,
        "dashboard_end": dashboard_end,
        "history_snapshot": history_snapshot,
        **build_department_today_detail_context(
            department=dashboard_department,
            target_date=today,
            next_url=request.get_full_path(),
        ),
    }
    return render(request, "performance/history.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_entry_edit(request: HttpRequest, entry_id: int) -> HttpResponse:
    entry = get_object_or_404(MemberDailyMetricEntry.objects.select_related("member", "department"), pk=entry_id)
    is_admin = bool(request.user.is_staff or request.user.is_superuser)
    if not is_admin:
        member = getattr(request.user, "member_profile", None)
        if member is None or member.id != entry.member_id:
            raise Http404
    status_message = ""
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    if request.method == "POST":
        previous_department_id = entry.department_id
        previous_entry_date = entry.entry_date
        form = PerformanceMemberDailyMetricEntryForm(request.POST, instance=entry)
        if form.is_valid():
            saved_entry = form.save(commit=False)
            saved_entry.input_source = MemberDailyMetricEntry.SOURCE_ADMIN
            saved_entry.save()
            if previous_department_id != saved_entry.department_id or previous_entry_date != saved_entry.entry_date:
                old_summary = DepartmentDailyMetricSummary.objects.filter(
                    department_id=previous_department_id,
                    entry_date=previous_entry_date,
                ).first()
                if old_summary:
                    old_summary.recalculate_from_entries()
            summary = DepartmentDailyMetricSummary.get_or_create_for_entry(entry=saved_entry)
            summary.recalculate_from_entries()
            if next_url:
                joiner = "&" if "?" in next_url else "?"
                return redirect(f"{next_url}{joiner}updated=entry")
            if is_admin:
                return redirect(f"{reverse('performance_index')}?updated=entry")
            return redirect(f"{reverse('performance_member_history')}?updated=entry")
        status_message = "入力内容を確認してください。"
    else:
        form = PerformanceMemberDailyMetricEntryForm(instance=entry)

    context = {
        "nav_items": performance_nav_items() if is_admin else performance_member_nav_items(is_admin=False),
        "form": form,
        "entry": entry,
        "status_message": status_message,
        "next_url": next_url,
        "back_url": next_url or (reverse("performance_index") if is_admin else reverse("performance_member_history")),
    }
    return render(request, "performance/entry_edit.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_entry_delete(request: HttpRequest, entry_id: int) -> HttpResponse:
    entry = get_object_or_404(MemberDailyMetricEntry.objects.select_related("member", "department"), pk=entry_id)
    is_admin = bool(request.user.is_staff or request.user.is_superuser)
    if not is_admin:
        member = getattr(request.user, "member_profile", None)
        if member is None or member.id != entry.member_id:
            raise Http404
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    fallback_url = (
        reverse("performance_member_history_detail", args=[entry.member_id, entry.department_id])
        if is_admin
        else reverse("performance_member_history")
    )
    back_url = performance_next_url(next_url, fallback=fallback_url)
    if request.method == "POST":
        previous_department_id = entry.department_id
        previous_entry_date = entry.entry_date
        entry.delete()
        old_summary = DepartmentDailyMetricSummary.objects.filter(
            department_id=previous_department_id,
            entry_date=previous_entry_date,
        ).first()
        if old_summary:
            old_summary.recalculate_from_entries()
        separator = "&" if "?" in back_url else "?"
        return redirect(f"{back_url}{separator}deleted=entry")
    raise Http404

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_transaction_edit(request: HttpRequest, transaction_id: int) -> HttpResponse:
    transaction = get_object_or_404(
        MemberMetricTransaction.objects.select_related("entry", "entry__member", "entry__department"),
        pk=transaction_id,
    )
    is_admin = bool(request.user.is_staff or request.user.is_superuser)
    if not is_admin:
        member = getattr(request.user, "member_profile", None)
        if member is None or member.id != transaction.entry.member_id:
            raise Http404
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    fallback_url = (
        reverse("performance_member_history_detail", args=[transaction.entry.member_id, transaction.entry.department_id])
        if is_admin
        else reverse("performance_member_history")
    )
    back_url = performance_next_url(next_url, fallback=fallback_url)
    status_message = ""
    if request.method == "POST":
        form = DairymetricsV2TransactionForm(
            request.POST,
            instance=transaction,
            department=transaction.entry.department,
        )
        if form.is_valid():
            saved_transaction = form.save(commit=False)
            saved_transaction.entry = transaction.entry
            saved_transaction.save()
            separator = "&" if "?" in back_url else "?"
            return redirect(f"{back_url}{separator}updated=transaction")
        status_message = "決済明細を確認してください。"
    else:
        form = DairymetricsV2TransactionForm(instance=transaction, department=transaction.entry.department)

    context = {
        "transaction": transaction,
        "entry": transaction.entry,
        "form": form,
        "status_message": status_message,
        "next_url": next_url,
        "back_url": back_url,
        "delete_url": reverse("performance_transaction_delete", args=[transaction.id]),
        "is_admin": is_admin,
        "is_wv": transaction.entry.department.code == "WV",
        "nav_items": performance_nav_items() if is_admin else performance_member_nav_items(is_admin=False),
    }
    return render(request, "performance/transaction_edit.html", context)

@require_performance_roles(ROLE_ADMIN)
def performance_transaction_delete(request: HttpRequest, transaction_id: int) -> HttpResponse:
    if request.method != "POST":
        raise Http404
    transaction = get_object_or_404(
        MemberMetricTransaction.objects.select_related("entry", "entry__member", "entry__department"),
        pk=transaction_id,
    )
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    fallback_url = reverse("performance_member_history_detail", args=[transaction.entry.member_id, transaction.entry.department_id])
    back_url = performance_next_url(next_url, fallback=fallback_url)
    transaction.delete()
    separator = "&" if "?" in back_url else "?"
    return redirect(f"{back_url}{separator}deleted=transaction")

@require_performance_roles(ROLE_ADMIN)
def performance_member_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    if request.method == "POST":
        selected_month = _parse_selected_month(request.GET.get("month"), default=timezone.localdate())
        current_period = _resolve_current_period(timezone.localdate())
        action = request.POST.get("action")
        if action == "save_month_target":
            form = MemberScopeTargetForm(
                request.POST,
                member=member,
                scope="month",
                department=department,
                target_month=selected_month,
            )
            if form.is_valid():
                form.save()
                query = f"?month={selected_month:%Y-%m}&saved=target"
                return redirect(f"{reverse('performance_member_detail', args=[member.id, department.id])}{query}")
        if action == "save_period_target" and current_period:
            form = MemberScopeTargetForm(
                request.POST,
                member=member,
                scope="period",
                department=department,
                period=current_period,
            )
            if form.is_valid():
                form.save()
                query = f"?month={selected_month:%Y-%m}&saved=target"
                return redirect(f"{reverse('performance_member_detail', args=[member.id, department.id])}{query}")
    context = build_member_dashboard_context(request=request, member=member, department=department, is_admin=True)
    return render(request, "performance/member_detail.html", context)

@require_performance_roles(ROLE_ADMIN)
def performance_member_history_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    context = build_member_history_context(request=request, member=member, department=department, is_admin=True)
    return render(request, "performance/member_history.html", context)

def _render_member_history_day_detail_response(
    *,
    request: HttpRequest,
    member,
    department,
    is_admin=False,
    readonly_member_view=False,
):
    selected_date = _parse_selected_date(request.GET.get("date"))
    if selected_date is None:
        raise Http404
    context = build_member_history_day_detail_context(
        member=member,
        department=department,
        selected_date=selected_date,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    return render(request, "performance/partials/member_history_day_detail_cards.html", context)

def _render_member_history_list_response(
    *,
    request: HttpRequest,
    member,
    department,
    is_admin=False,
    readonly_member_view=False,
):
    context = build_member_history_list_context(
        request=request,
        member=member,
        department=department,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    return render(request, "performance/partials/member_history_day_detail_cards.html", context)

@require_performance_roles(ROLE_ADMIN)
def performance_member_history_detail_day_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_history_day_detail_response(request=request, member=member, department=department, is_admin=True)

@require_performance_roles(ROLE_ADMIN)
def performance_member_history_detail_list(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_history_list_response(request=request, member=member, department=department, is_admin=True)

def _render_member_day_detail_response(
    *,
    request: HttpRequest,
    member,
    department,
    is_admin=False,
    readonly_member_view=False,
):
    selected_date = _parse_selected_date(request.GET.get("date"))
    if selected_date is None:
        raise Http404
    entry_rows = build_member_dashboard_entry_rows(
        member=member,
        department=department,
        month_start=selected_date,
        month_end=selected_date,
        field_count_text=_field_count_text,
        field_amount_text=_field_amount_text,
    )
    adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date=selected_date,
        ).order_by("-target_date", "-created_at")
    )
    reset_url = (
        reverse("performance_member_insight", args=[member.id, department.id])
        if readonly_member_view
        else reverse("performance_member_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_dashboard")
    )
    context = build_member_dashboard_detail_context(
        member=member,
        department=department,
        entry_rows=entry_rows,
        adjustment_rows=adjustment_rows,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
        selected_date=selected_date,
        reset_url=reset_url,
    )
    can_edit = can_edit_member_performance(is_admin=is_admin, readonly_member_view=readonly_member_view)
    context["can_edit"] = can_edit
    if can_edit:
        attach_transaction_edit_urls(entry_rows=context["recent_entry_rows"], next_url=reset_url)
        for row in context["recent_entry_rows"]:
            row["edit_url"] = (
                f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
                f"?{urlencode({'next': reset_url})}"
            )
            row["delete_url"] = (
                f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
                f"?{urlencode({'next': reset_url})}"
            )
    return render(request, "performance/partials/member_day_detail_cards.html", context)

def _render_member_recent_detail_response(
    *,
    request: HttpRequest,
    member,
    department,
    is_admin=False,
    readonly_member_view=False,
):
    context = build_member_recent_detail_context(
        request=request,
        member=member,
        department=department,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
    )
    return render(request, "performance/partials/member_day_detail_cards.html", context)

@require_performance_roles(ROLE_ADMIN)
def performance_member_detail_day_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_day_detail_response(request=request, member=member, department=department, is_admin=True)

@require_performance_roles(ROLE_ADMIN)
def performance_member_detail_recent_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_recent_detail_response(request=request, member=member, department=department, is_admin=True)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_insight(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    context = build_member_dashboard_context(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
    )
    context["readonly_member_view"] = True
    context["can_edit"] = can_edit_member_performance(
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )
    context["nav_items"] = performance_member_page_nav_links(
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )
    context["detail_history_url"] = reverse("performance_member_history_insight", args=[member.id, department.id])
    context["recent_detail_ajax_url"] = reverse("performance_member_insight_recent_detail", args=[member.id, department.id])
    return render(request, "performance/member_detail.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_insight_day_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_day_detail_response(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_insight_recent_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_recent_detail_response(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history_insight(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    context = build_member_history_context(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
    )
    context["readonly_member_view"] = True
    context["can_edit"] = can_edit_member_performance(
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )
    context["nav_items"] = performance_member_page_nav_links(
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )
    context["detail_ajax_url"] = reverse("performance_member_history_insight_list", args=[member.id, department.id])
    return render(request, "performance/member_history.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history_insight_day_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_history_day_detail_response(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history_insight_list(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    return _render_member_history_list_response(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_dashboard(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        return redirect("performance_index")
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    if request.method == "POST":
        selected_month = _parse_selected_month(request.GET.get("month"), default=timezone.localdate())
        current_period = _resolve_current_period(timezone.localdate())
        action = request.POST.get("action")
        if action == "save_month_target":
            form = MemberScopeTargetForm(
                request.POST,
                member=member,
                scope="month",
                department=department,
                target_month=selected_month,
            )
            if form.is_valid():
                form.save()
                return redirect(f"{reverse('performance_member_dashboard')}?month={selected_month:%Y-%m}&saved=target")
        if action == "save_period_target" and current_period:
            form = MemberScopeTargetForm(
                request.POST,
                member=member,
                scope="period",
                department=department,
                period=current_period,
            )
            if form.is_valid():
                form.save()
                return redirect(f"{reverse('performance_member_dashboard')}?month={selected_month:%Y-%m}&saved=target")
    context = build_member_dashboard_context(request=request, member=member, department=department, is_admin=False)
    return render(request, "performance/member_detail.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_dashboard_day_detail(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        raise Http404
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    return _render_member_day_detail_response(request=request, member=member, department=department, is_admin=False)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_dashboard_recent_detail(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        raise Http404
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    return _render_member_recent_detail_response(request=request, member=member, department=department, is_admin=False)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        return redirect("performance_index")
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    context = build_member_history_context(request=request, member=member, department=department, is_admin=False)
    return render(request, "performance/member_history.html", context)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history_list(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        raise Http404
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    return _render_member_history_list_response(request=request, member=member, department=department, is_admin=False)

@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history_day_detail(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        raise Http404
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    return _render_member_history_day_detail_response(request=request, member=member, department=department, is_admin=False)

@require_performance_roles(ROLE_ADMIN)
def performance_past_entry_create(request: HttpRequest) -> HttpResponse:
    selection_source = request.POST if request.method == "POST" else request.GET
    selection_form = PerformancePastEntrySelectionForm(selection_source or None)
    selected_department = None
    selected_member = None
    selected_entry_date = None
    existing_entry = None
    status_message = ""
    create_form = PerformancePastEntryCreateForm(request.POST or None)
    transactions_payload_value = request.POST.get("transactions_payload", "[]") if request.method == "POST" else "[]"
    transaction_errors = []
    transaction_preview = []
    cleaned_transactions = []
    existing_entry_next_url = ""

    if selection_form.is_valid():
        selected_department = selection_form.cleaned_data["department"]
        selected_member = selection_form.cleaned_data["member"]
        selected_entry_date = selection_form.cleaned_data["entry_date"]
        existing_entry = MemberDailyMetricEntry.objects.filter(
            member=selected_member,
            department=selected_department,
            entry_date=selected_entry_date,
        ).first()
        existing_entry_next_url = (
            f"{reverse('performance_past_entry_create')}?"
            f"{urlencode({'department': selected_department.id, 'member': selected_member.id, 'entry_date': selected_entry_date.strftime('%Y-%m-%d')})}"
        )

    transaction_form = DairymetricsV2TransactionForm(department=selected_department)

    if request.method == "POST" and selection_form.is_valid() and create_form.is_valid():
        try:
            transaction_payload_rows = parse_transactions_payload(transactions_payload_value)
        except ValueError as exc:
            transaction_errors = [str(exc)]
            transaction_payload_rows = []
        else:
            transaction_preview = transaction_preview_rows(
                department=selected_department,
                payload_rows=transaction_payload_rows,
            )
            cleaned_transactions, transaction_errors = normalize_transaction_payloads(
                department=selected_department,
                payload_rows=transaction_payload_rows,
            )
        if existing_entry is not None:
            status_message = "その日の実績はすでに登録されています。既存データを修正してください。"
        elif not transaction_errors:
            try:
                create_past_entry_with_transactions(
                    member=selected_member,
                    department=selected_department,
                    entry_date=selected_entry_date,
                    location_name=create_form.cleaned_data["location_name"],
                    approach_count=create_form.cleaned_data["approach_count"],
                    communication_count=create_form.cleaned_data["communication_count"],
                    transactions=cleaned_transactions,
                )
            except ValueError as exc:
                status_message = str(exc)
            else:
                query = urlencode(
                    {
                        "department": selected_department.id,
                        "member": selected_member.id,
                        "saved": 1,
                    }
                )
                return redirect(f"{reverse('performance_past_entry_create')}?{query}")
        elif not status_message:
            status_message = "決済明細を確認してください。"
    elif request.GET.get("saved") == "1":
        status_message = "過去実績を登録しました。"

    context = {
        "nav_items": performance_nav_items(),
        "selection_form": selection_form,
        "create_form": create_form,
        "transaction_form": transaction_form,
        "selected_department": selected_department,
        "selected_member": selected_member,
        "selected_entry_date": selected_entry_date,
        "existing_entry": existing_entry,
        "existing_entry_next_url": existing_entry_next_url,
        "status_message": status_message,
        "transactions_payload_value": transactions_payload_value,
        "transaction_preview": transaction_preview,
        "transaction_errors": transaction_errors,
        "is_wv_department": bool(selected_department and selected_department.code == "WV"),
        "age_band_choices": MemberMetricTransaction.AGE_BAND_CHOICES,
        "gender_choices": MemberMetricTransaction.GENDER_CHOICES,
        "nationality_choices": MemberMetricTransaction.NATIONALITY_CHOICES,
        "wv_result_type_choices": MemberMetricTransaction.WV_RESULT_TYPE_CHOICES,
        "wv_cs_unit_amount": MemberMetricTransaction.WV_CS_UNIT_AMOUNT,
    }
    return render(request, "performance/past_entry_create.html", context)

@require_performance_roles(ROLE_ADMIN)
def performance_past_entry_member_options(request: HttpRequest) -> HttpResponse:
    department_id = request.GET.get("department")
    if not department_id or not department_id.isdigit():
        return JsonResponse({"options": []})
    department = Department.objects.filter(pk=int(department_id), is_active=True).first()
    if department is None:
        return JsonResponse({"options": []})
    queryset = Member.objects.filter(department_links__department=department).distinct().order_by("name")
    un_code = "".join(character for character in request.GET.get("un_code", "").strip() if character.isdigit())[:5]
    if un_code:
        queryset = queryset.filter(un_activity_code__startswith=un_code)
    options = list(
        queryset
        .distinct()
        .order_by("name")
        .values("id", "name", "un_activity_code")
    )
    return JsonResponse({"options": options})

@require_performance_roles(ROLE_ADMIN)
def performance_summary_delete(request: HttpRequest, summary_id: int) -> HttpResponse:
    if request.method != "POST":
        raise Http404
    summary = get_object_or_404(
        DepartmentDailyMetricSummary.objects.select_related("department"),
        pk=summary_id,
    )
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("performance_admin_entries")
    has_entries = MemberDailyMetricEntry.objects.filter(
        department=summary.department,
        entry_date=summary.entry_date,
    ).exists()
    if not has_entries:
        summary.delete()
        separator = "&" if "?" in next_url else "?"
        return redirect(f"{performance_next_url(next_url, fallback=reverse('performance_admin_entries'))}{separator}deleted=summary")
    separator = "&" if "?" in next_url else "?"
    return redirect(f"{performance_next_url(next_url, fallback=reverse('performance_admin_entries'))}{separator}status=summary_not_empty")

@require_performance_roles(ROLE_ADMIN)
def performance_adjustments(request: HttpRequest) -> HttpResponse:
    status_message = ""
    edit_adjustment = None
    edit_id = request.GET.get("edit")
    if edit_id:
        edit_adjustment = get_object_or_404(MetricAdjustment, pk=edit_id)

    filter_data = request.GET.copy()
    if not filter_data:
        filter_data["date_from"] = ""
        filter_data["date_to"] = ""
    filter_form = PerformanceEntryFilterForm(filter_data)
    adjustments_queryset = MetricAdjustment.objects.none()
    if filter_form.is_valid():
        adjustments_queryset = filtered_adjustments_queryset(filter_form.cleaned_data)

    if request.method == "POST":
        adjustment_id = request.POST.get("adjustment_id")
        edit_adjustment = get_object_or_404(MetricAdjustment, pk=adjustment_id) if adjustment_id else None
        form = PerformanceMetricAdjustmentForm(request.POST, instance=edit_adjustment)
        if form.is_valid():
            record = form.save(commit=False)
            if record.created_by_id is None:
                record.created_by = request.user
            record.save()
            return redirect(f"{reverse('performance_adjustments')}?saved=1")
        status_message = "入力内容を確認してください。"
    else:
        form = PerformanceMetricAdjustmentForm(instance=edit_adjustment)
        if request.GET.get("saved") == "1":
            status_message = "補正実績を保存しました。"

    list_filter_data = request.GET.copy()
    if "department" not in list_filter_data:
        list_filter_data["department"] = ""
    if "q" not in list_filter_data:
        list_filter_data["q"] = ""
    list_filter_form = PerformanceAdjustmentListFilterForm(list_filter_data)
    if list_filter_form.is_valid():
        adjustments_queryset = combined_adjustment_list_rows(list_filter_form.cleaned_data)
    else:
        adjustments_queryset = []

    paginator = Paginator(adjustments_queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    member_options = {}
    department_code_map = {
        str(department.id): department.code
        for department in Department.objects.filter(is_active=True).order_by("code")
    }
    for member in (
        Member.objects.active()
        .filter(department_links__department__is_active=True)
        .prefetch_related("department_links__department")
        .order_by("name", "id")
        .distinct()
    ):
        for link in member.department_links.all():
            if link.department_id is None or not link.department.is_active:
                continue
            member_options.setdefault(str(link.department_id), []).append(
                {
                    "id": member.id,
                    "name": member.name,
                    "un_activity_code": member.un_activity_code or "",
                }
            )
    list_context = {
        "adjustments": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
    }
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "list_html": render_to_string(
                    "performance/partials/adjustment_list.html",
                    list_context,
                    request=request,
                )
            }
        )

    context = {
        "nav_items": performance_nav_items(),
        "filter_form": filter_form,
        "list_filter_form": list_filter_form,
        "form": form,
        "edit_adjustment": edit_adjustment,
        "status_message": status_message,
        "page_obj": page_obj,
        "paginator": paginator,
        "adjustments": page_obj.object_list,
        "member_options": member_options,
        "department_code_map": department_code_map,
    }
    return render(request, "performance/adjustments.html", context)

@require_performance_roles(ROLE_ADMIN)
def performance_adjustment_delete(request: HttpRequest, adjustment_id: int) -> HttpResponse:
    adjustment = get_object_or_404(MetricAdjustment, pk=adjustment_id)
    if request.method == "POST":
        adjustment.delete()
    return redirect(reverse("performance_adjustments"))

@require_performance_roles(ROLE_ADMIN)
def performance_cancellation_delete(request: HttpRequest, cancellation_id: int) -> HttpResponse:
    cancellation = get_object_or_404(WVMetricCancellation, pk=cancellation_id)
    if request.method == "POST":
        cancellation.delete()
    return redirect(reverse("performance_adjustments"))
