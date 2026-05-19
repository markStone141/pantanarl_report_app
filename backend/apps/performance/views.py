from functools import wraps
from dataclasses import dataclass
from datetime import date, timedelta

from django.contrib.auth import login as auth_login
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, resolve_request_role
from apps.accounts.models import Department, Member, MemberDepartment
from apps.dairymetrics.forms import DairyMetricsLoginForm, MemberScopeTargetForm
from apps.dairymetrics.models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_department_final_actual_totals_by_codes,
    collect_member_final_actual_totals,
)
from apps.targets.models import (
    DepartmentMonthTarget,
    DepartmentPeriodTarget,
    MonthTargetMetricValue,
    Period,
    PeriodTargetMetricValue,
)

from .forms import PerformanceEntryFilterForm, PerformanceMemberDailyMetricEntryForm, PerformanceMetricAdjustmentForm


User = get_user_model()


@dataclass(frozen=True)
class PerformanceHistoryScope:
    scope: str
    label: str
    start_date: date
    end_date: date
    month_start: date | None = None
    period: Period | None = None


def _performance_redirect_for_user(user, *, fallback=""):
    if fallback and isinstance(fallback, str) and fallback.startswith("/performance/"):
        return redirect(fallback)
    if user.is_staff or user.is_superuser:
        return redirect("performance_index")
    return redirect("performance_member_dashboard")


def require_performance_roles(*allowed_roles: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            role = resolve_request_role(request)
            if role not in allowed_roles:
                next_url = request.get_full_path()
                query = urlencode({"next": next_url}) if next_url else ""
                login_url = reverse("performance_login")
                return redirect(f"{login_url}?{query}" if query else login_url)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def _performance_nav_items():
    return [
        ("performance_index", "実績管理ダッシュボード"),
        ("performance_history", "実績閲覧"),
        ("performance_adjustments", "補正実績入力"),
        ("dashboard_index", "総合管理者ページ"),
    ]


def _performance_member_nav_items(*, is_admin=False):
    if is_admin:
        return [
            ("performance_index", "実績管理ダッシュボード"),
            ("performance_history", "実績閲覧"),
        ]
    return [
        ("performance_member_dashboard", "実績管理ダッシュボード"),
        ("performance_member_history", "実績閲覧"),
    ]


def _resolve_performance_member_department_or_404(*, member, department_id):
    department = get_object_or_404(Department, pk=department_id, is_active=True)
    if not MemberDepartment.objects.filter(member=member, department=department).exists() and member.default_department_id != department.id:
        raise Http404
    return department


def performance_login(request: HttpRequest) -> HttpResponse:
    role = resolve_request_role(request)
    if role in {ROLE_ADMIN, ROLE_REPORT} and request.user.is_authenticated:
        return _performance_redirect_for_user(request.user, fallback=request.GET.get("next", ""))

    form = DairyMetricsLoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.user)
        return _performance_redirect_for_user(form.user, fallback=request.POST.get("next", ""))

    return render(
        request,
        "performance/login.html",
        {
            "form": form,
            "next": request.GET.get("next", ""),
        },
    )


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


def _filtered_adjustments_queryset(cleaned_data):
    queryset = MetricAdjustment.objects.select_related("member", "department", "created_by").order_by("-target_date", "-created_at")
    department = cleaned_data.get("department")
    member = cleaned_data.get("member")
    date_from = cleaned_data.get("date_from")
    date_to = cleaned_data.get("date_to")
    if department:
        queryset = queryset.filter(department=department)
    if member:
        queryset = queryset.filter(member=member)
    if date_from:
        queryset = queryset.filter(target_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(target_date__lte=date_to)
    return queryset


def _build_adjustment_totals_map(entries):
    entries = list(entries)
    if not entries:
        return {}
    member_ids = {entry.member_id for entry in entries}
    department_ids = {entry.department_id for entry in entries}
    dates = {entry.entry_date for entry in entries}
    rows = (
        MetricAdjustment.objects.filter(
            member_id__in=member_ids,
            department_id__in=department_ids,
            target_date__in=dates,
        )
        .values("member_id", "department_id", "target_date")
        .annotate(
            result_count_total=Sum("result_count"),
            support_amount_total=Sum("support_amount"),
            return_postal_count_total=Sum("return_postal_count"),
            return_postal_amount_total=Sum("return_postal_amount"),
            return_qr_count_total=Sum("return_qr_count"),
            return_qr_amount_total=Sum("return_qr_amount"),
            cs_count_total=Sum("cs_count"),
            refugee_count_total=Sum("refugee_count"),
        )
    )
    totals_map = {}
    for row in rows:
        totals_map[(row["member_id"], row["department_id"], row["target_date"])] = {
            "result_count": int(row["result_count_total"] or 0),
            "support_amount": int(row["support_amount_total"] or 0),
            "return_postal_count": int(row["return_postal_count_total"] or 0),
            "return_postal_amount": int(row["return_postal_amount_total"] or 0),
            "return_qr_count": int(row["return_qr_count_total"] or 0),
            "return_qr_amount": int(row["return_qr_amount_total"] or 0),
            "cs_count": int(row["cs_count_total"] or 0),
            "refugee_count": int(row["refugee_count_total"] or 0),
        }
    return totals_map


def _count_text(entry, adjustment_totals):
    if entry.department.code == "WV":
        total_cs = int(entry.cs_count or 0) + int(adjustment_totals["cs_count"])
        total_refugee = int(entry.refugee_count or 0) + int(adjustment_totals["refugee_count"])
        return f"CS {total_cs} / 難民 {total_refugee}"
    total_count = _entry_final_count_value(entry=entry, adjustment_totals=adjustment_totals)
    return f"{total_count}件"


def _amount_text(entry, adjustment_totals):
    total_amount = _entry_final_amount_value(entry=entry, adjustment_totals=adjustment_totals)
    return f"{total_amount:,}円"


def _entry_final_count_value(*, entry, adjustment_totals):
    if entry.department.code == "WV":
        return (
            int(entry.cs_count or 0)
            + int(entry.refugee_count or 0)
            + int(adjustment_totals["cs_count"])
            + int(adjustment_totals["refugee_count"])
        )
    return (
        int(entry.result_count or 0)
        + int(adjustment_totals["result_count"])
        + int(adjustment_totals["return_postal_count"])
        + int(adjustment_totals["return_qr_count"])
    )


def _entry_final_amount_value(*, entry, adjustment_totals):
    return (
        int(entry.support_amount or 0)
        + int(adjustment_totals["support_amount"])
        + int(adjustment_totals["return_postal_amount"])
        + int(adjustment_totals["return_qr_amount"])
    )


def _resolve_current_period(today):
    return (
        Period.objects.filter(start_date__lte=today, end_date__gte=today)
        .order_by("-month", "start_date", "id")
        .first()
        or Period.objects.order_by("-end_date", "-start_date", "-id").first()
    )


def _resolve_month_target_amounts_by_code(*, departments, target_month):
    target_codes = [department.code for department in departments]
    metric_rows = (
        MonthTargetMetricValue.objects.filter(
            department__code__in=target_codes,
            target_month=target_month,
            metric__code="amount",
        )
        .values("department__code", "value")
    )
    target_map = {row["department__code"]: int(row["value"] or 0) for row in metric_rows}
    fallback_rows = (
        DepartmentMonthTarget.objects.filter(
            department__code__in=target_codes,
            target_month=target_month,
        )
        .values("department__code", "target_amount")
    )
    for row in fallback_rows:
        target_map.setdefault(row["department__code"], int(row["target_amount"] or 0))
    return target_map


def _resolve_period_target_amounts_by_code(*, departments, period):
    if not period:
        return {}
    target_codes = [department.code for department in departments]
    metric_rows = (
        PeriodTargetMetricValue.objects.filter(
            department__code__in=target_codes,
            period=period,
            metric__code="amount",
        )
        .values("department__code", "value")
    )
    target_map = {row["department__code"]: int(row["value"] or 0) for row in metric_rows}
    fallback_rows = (
        DepartmentPeriodTarget.objects.filter(
            department__code__in=target_codes,
            period=period,
        )
        .values("department__code", "target_amount")
    )
    for row in fallback_rows:
        target_map.setdefault(row["department__code"], int(row["target_amount"] or 0))
    return target_map


def _collect_adjustment_amounts_by_codes(*, target_codes, start_date, end_date):
    if not target_codes:
        return {}
    rows = (
        MetricAdjustment.objects.filter(
            department__code__in=target_codes,
            target_date__range=(start_date, end_date),
        )
        .values("department__code")
        .annotate(
            support_amount_total=Sum("support_amount"),
            return_postal_amount_total=Sum("return_postal_amount"),
            return_qr_amount_total=Sum("return_qr_amount"),
        )
    )
    return {
        row["department__code"]: (
            int(row["support_amount_total"] or 0)
            + int(row["return_postal_amount_total"] or 0)
            + int(row["return_qr_amount_total"] or 0)
        )
        for row in rows
    }


def _progress_rate(actual, target):
    if target <= 0:
        return None
    return round((actual / target) * 100, 1)


def _build_progress_card(*, label, actual_amount, target_amount, summary_text, base_actual_amount=0, adjustment_amount=0):
    rate = _progress_rate(actual_amount, target_amount)
    remaining_amount = max(int(target_amount or 0) - int(actual_amount or 0), 0)
    base_actual_amount = int(base_actual_amount or 0)
    adjustment_amount = int(adjustment_amount or 0)
    target_amount = int(target_amount or 0)
    if target_amount > 0:
        capped_base_amount = min(base_actual_amount, target_amount)
        capped_adjustment_amount = min(adjustment_amount, max(target_amount - capped_base_amount, 0))
        remaining_chart_amount = max(target_amount - capped_base_amount - capped_adjustment_amount, 0)
        chart_values = [capped_base_amount, capped_adjustment_amount, remaining_chart_amount]
    else:
        chart_values = [0, 0, 100]
    return {
        "label": label,
        "actual_amount": actual_amount,
        "actual_amount_text": f"{actual_amount:,}円",
        "base_actual_amount_text": f"{base_actual_amount:,}円",
        "adjustment_amount_text": f"{adjustment_amount:,}円",
        "target_amount": target_amount,
        "target_amount_text": f"{target_amount:,}円",
        "remaining_amount_text": f"{remaining_amount:,}円",
        "rate": rate,
        "rate_text": "-" if rate is None else f"{rate}%",
        "chart_values": chart_values,
        "summary_text": summary_text,
    }


def _build_contribution_summary(*, member_actual_amount, department_actual_amount):
    department_amount = int(department_actual_amount or 0)
    member_amount = int(member_actual_amount or 0)
    if department_amount <= 0:
        return {
            "rate": None,
            "rate_text": "-",
            "detail_text": "全体実績がまだありません。",
        }
    rate = round((member_amount / department_amount) * 100, 1)
    return {
        "rate": rate,
        "rate_text": f"{rate}%",
        "detail_text": f"{member_amount:,}円 / {department_amount:,}円",
    }


def _build_member_target_progress(*, label, actual_amount, target_amount):
    rate = _progress_rate(actual_amount, target_amount)
    return {
        "label": label,
        "actual_amount_text": f"{actual_amount:,}円",
        "target_amount_text": f"{target_amount:,}円",
        "rate_text": "-" if rate is None else f"{rate}%",
    }


def _build_activity_member_rows(entries):
    rows = []
    for entry in entries:
        rows.append(
            {
                "member_name": entry.member.name,
                "department_code": entry.department.code,
                "updated_at": timezone.localtime(entry.updated_at).strftime("%H:%M"),
                "amount_text": f"{int(entry.support_amount or 0):,}円",
                "count_text": (
                    f"CS {int(entry.cs_count or 0)} / 難民 {int(entry.refugee_count or 0)}"
                    if entry.department.code == "WV"
                    else f"{int(entry.result_count or 0)}件"
                ),
            }
        )
    return rows


def _build_scoped_member_cards(*, members, selected_department, scope):
    cards = []
    scope_metric_label = {
        "month": "月累計",
        "period": "路程累計",
        "range": "期間累計",
    }.get(scope.scope, "累計")
    for member in members:
        department = _resolve_member_card_department(member=member, selected_department=selected_department)
        if department is None:
            continue
        scoped_totals = collect_member_final_actual_totals(
            member,
            department,
            scope.start_date,
            scope.end_date,
            include_adjustments=True,
        )
        scoped_entries = list(
            MemberDailyMetricEntry.objects.filter(
                member=member,
                department=department,
                entry_date__range=(scope.start_date, scope.end_date),
            )
            .select_related("member", "department")
            .order_by("-entry_date", "-id")[:3]
        )
        latest_adjustment_totals = _build_adjustment_totals_map(scoped_entries)
        latest_final_counts = []
        for latest_entry in scoped_entries:
            latest_totals = latest_adjustment_totals.get(
                (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
                {
                    "result_count": 0,
                    "support_amount": 0,
                    "return_postal_count": 0,
                    "return_postal_amount": 0,
                    "return_qr_count": 0,
                    "return_qr_amount": 0,
                    "cs_count": 0,
                    "refugee_count": 0,
                },
            )
            latest_final_counts.append(_entry_final_count_value(entry=latest_entry, adjustment_totals=latest_totals))
        zero_streak_warning = len(latest_final_counts) == 3 and all(count == 0 for count in latest_final_counts)
        active_streak_good = len(latest_final_counts) == 3 and all(count >= 1 for count in latest_final_counts)
        if scoped_entries:
            latest_entry = scoped_entries[0]
            latest_totals = latest_adjustment_totals.get(
                (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
                {
                    "result_count": 0,
                    "support_amount": 0,
                    "return_postal_count": 0,
                    "return_postal_amount": 0,
                    "return_qr_count": 0,
                    "return_qr_amount": 0,
                    "cs_count": 0,
                    "refugee_count": 0,
                },
            )
            updated_at_text = timezone.localtime(latest_entry.updated_at).strftime("%H:%M")
            recent_date_text = latest_entry.entry_date.strftime("%Y/%m/%d")
            recent_amount_text = _amount_text(latest_entry, latest_totals)
            recent_count_text = _count_text(latest_entry, latest_totals)
            recent_sort_date = latest_entry.entry_date
        else:
            updated_at_text = "実績なし"
            recent_date_text = "-"
            recent_amount_text = "-"
            recent_count_text = "-"
            recent_sort_date = None
        cards.append(
            {
                "member_name": member.name,
                "department_code": department.code,
                "updated_at": updated_at_text,
                "scope_label": scope_metric_label,
                "scope_amount_text": _final_amount_text(totals=scoped_totals),
                "scope_count_text": _final_count_text(department_code=department.code, totals=scoped_totals),
                "recent_date_text": recent_date_text,
                "recent_amount_text": recent_amount_text,
                "recent_count_text": recent_count_text,
                "recent_sort_date": recent_sort_date,
                "zero_streak_warning": zero_streak_warning,
                "zero_streak_text": "3稼働連続0件" if zero_streak_warning else "",
                "active_streak_good": active_streak_good,
                "active_streak_text": "3稼働連続1件以上" if active_streak_good else "",
                "detail_url": reverse("performance_member_insight", args=[member.id, department.id]),
            }
        )
    cards.sort(
        key=lambda card: (
            card["recent_sort_date"] is not None,
            card["recent_sort_date"] or date.min,
            card["member_name"],
        ),
        reverse=True,
    )
    return cards


def _final_count_text(*, department_code, totals):
    if department_code == "WV":
        total_cs = int(totals.get("cs_count") or 0)
        total_refugee = int(totals.get("refugee_count") or 0)
        return f"CS {total_cs} / 難民 {total_refugee}"
    total_count = (
        int(totals.get("result_count") or 0)
        + int(totals.get("return_postal_count") or 0)
        + int(totals.get("return_qr_count") or 0)
    )
    return f"{total_count}件"


def _final_count_value(*, department_code, totals):
    if department_code == "WV":
        return int(totals.get("cs_count") or 0) + int(totals.get("refugee_count") or 0)
    return (
        int(totals.get("result_count") or 0)
        + int(totals.get("return_postal_count") or 0)
        + int(totals.get("return_qr_count") or 0)
    )


def _final_amount_text(*, totals):
    total_amount = (
        int(totals.get("support_amount") or 0)
        + int(totals.get("return_postal_amount") or 0)
        + int(totals.get("return_qr_amount") or 0)
    )
    return f"{total_amount:,}円"


def _resolve_member_card_department(*, member, selected_department=None):
    if selected_department is not None:
        return selected_department
    if member.default_department_id and member.default_department and member.default_department.is_active:
        return member.default_department
    return (
        Department.objects.filter(member_links__member=member, is_active=True)
        .order_by("code", "id")
        .first()
    )


def _resolve_default_dashboard_department():
    return (
        Department.objects.filter(is_active=True, code="UN").first()
        or Department.objects.filter(is_active=True).order_by("code", "id").first()
    )


def _parse_selected_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _resolve_performance_history_scope(*, today, scope_value, requested_month=None, requested_period=None, requested_start=None, requested_end=None):
    if scope_value == "period" and requested_period is not None:
        return PerformanceHistoryScope(
            scope="period",
            label=requested_period.name,
            start_date=requested_period.start_date,
            end_date=min(requested_period.end_date, today),
            period=requested_period,
        )
    if scope_value == "range":
        start_date = requested_start or (today - timedelta(days=29))
        end_date = requested_end or today
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return PerformanceHistoryScope(
            scope="range",
            label=f"{start_date:%Y/%m/%d} - {end_date:%Y/%m/%d}",
            start_date=start_date,
            end_date=end_date,
        )
    month_start = requested_month or today.replace(day=1)
    return PerformanceHistoryScope(
        scope="month",
        label=month_start.strftime("%Y/%m"),
        start_date=month_start,
        end_date=min(_month_end(month_start), today),
        month_start=month_start,
    )


def _build_active_member_cards(*, members, today, target_month, target_period, selected_department=None):
    cards = []
    for member in members:
        department = _resolve_member_card_department(member=member, selected_department=selected_department)
        if department is None:
            continue
        entry = (
            MemberDailyMetricEntry.objects.select_related("member", "department")
            .filter(member=member, department=department)
            .order_by("-entry_date", "-id")
            .first()
        )
        month_totals = collect_member_final_actual_totals(
            member,
            department,
            target_month,
            today,
            include_adjustments=True,
        )
        period_totals = collect_member_final_actual_totals(
            member,
            department,
            target_period.start_date if target_period else today,
            min(target_period.end_date, today) if target_period else today,
            include_adjustments=True,
        )
        latest_entries = list(
            MemberDailyMetricEntry.objects.filter(member=member, department=department)
            .order_by("-entry_date", "-id")[:3]
        )
        latest_adjustment_totals = _build_adjustment_totals_map(latest_entries)
        latest_final_counts = []
        for latest_entry in latest_entries:
            latest_totals = latest_adjustment_totals.get(
                (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
                {
                    "result_count": 0,
                    "support_amount": 0,
                    "return_postal_count": 0,
                    "return_postal_amount": 0,
                    "return_qr_count": 0,
                    "return_qr_amount": 0,
                    "cs_count": 0,
                    "refugee_count": 0,
                },
            )
            latest_final_counts.append(_entry_final_count_value(entry=latest_entry, adjustment_totals=latest_totals))
        zero_streak_warning = len(latest_final_counts) == 3 and all(count == 0 for count in latest_final_counts)
        active_streak_good = len(latest_final_counts) == 3 and all(count >= 1 for count in latest_final_counts)
        if entry is not None:
            recent_totals = _build_adjustment_totals_map([entry]).get(
                (entry.member_id, entry.department_id, entry.entry_date),
                {
                    "result_count": 0,
                    "support_amount": 0,
                    "return_postal_count": 0,
                    "return_postal_amount": 0,
                    "return_qr_count": 0,
                    "return_qr_amount": 0,
                    "cs_count": 0,
                    "refugee_count": 0,
                },
            )
            updated_at_text = timezone.localtime(entry.updated_at).strftime("%H:%M")
            recent_date_text = entry.entry_date.strftime("%Y/%m/%d")
            recent_amount_text = _amount_text(entry, recent_totals)
            recent_count_text = _count_text(entry, recent_totals)
            recent_sort_date = entry.entry_date
        else:
            updated_at_text = "実績なし"
            recent_date_text = "-"
            recent_amount_text = "-"
            recent_count_text = "-"
            recent_sort_date = None
        cards.append(
            {
                "member_name": member.name,
                "department_code": department.code,
                "updated_at": updated_at_text,
                "month_amount_text": _final_amount_text(totals=month_totals),
                "month_count_text": _final_count_text(department_code=department.code, totals=month_totals),
                "period_amount_text": _final_amount_text(totals=period_totals),
                "period_count_text": _final_count_text(department_code=department.code, totals=period_totals),
                "recent_date_text": recent_date_text,
                "recent_amount_text": recent_amount_text,
                "recent_count_text": recent_count_text,
                "recent_sort_date": recent_sort_date,
                "zero_streak_warning": zero_streak_warning,
                "zero_streak_text": "3稼働連続0件" if zero_streak_warning else "",
                "active_streak_good": active_streak_good,
                "active_streak_text": "3稼働連続1件以上" if active_streak_good else "",
                "detail_url": reverse("performance_member_insight", args=[member.id, department.id]),
            }
        )
    cards.sort(
        key=lambda card: (
            card["recent_sort_date"] is not None,
            card["recent_sort_date"] or date.min,
            card["member_name"],
        ),
        reverse=True,
    )
    return cards


def _build_performance_dashboard_snapshot(*, department=None, target_month=None, period=None):
    today = timezone.localdate()
    target_month = target_month or today.replace(day=1)
    period = period or _resolve_current_period(today)
    active_entries = MemberDailyMetricEntry.objects.select_related("member", "department").filter(entry_date=today)
    if department:
        active_entries = active_entries.filter(department=department)
        departments = [department]
    else:
        department_ids = list(active_entries.order_by("department__code").values_list("department_id", flat=True).distinct())
        departments = list(Department.objects.filter(id__in=department_ids).order_by("code"))
    active_entries = list(active_entries.order_by("department__code", "member__name"))
    activity_in_progress = [entry for entry in active_entries if not entry.activity_closed]
    activity_finished = [entry for entry in active_entries if entry.activity_closed]
    if department:
        active_members = list(
            Member.objects.active()
            .filter(department_links__department=department, department_links__department__is_active=True)
            .select_related("default_department")
            .distinct()
            .order_by("name", "id")
        )
    else:
        active_members = list(
            Member.objects.active()
            .filter(Q(default_department__is_active=True) | Q(department_links__department__is_active=True))
            .select_related("default_department")
            .distinct()
            .order_by("name", "id")
        )

    target_codes = [department.code for department in departments]

    month_totals_by_code = collect_department_final_actual_totals_by_codes(
        target_codes=target_codes,
        start_date=target_month,
        end_date=today,
        include_adjustments=True,
    )
    period_totals_by_code = collect_department_final_actual_totals_by_codes(
        target_codes=target_codes,
        start_date=period.start_date if period else today,
        end_date=min(period.end_date, today) if period else today,
        include_adjustments=True,
    ) if target_codes else {}
    month_adjustment_amounts = _collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=target_month,
        end_date=today,
    )
    period_adjustment_amounts = _collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=period.start_date if period else today,
        end_date=min(period.end_date, today) if period else today,
    ) if target_codes else {}

    month_target_amounts = _resolve_month_target_amounts_by_code(departments=departments, target_month=target_month)
    period_target_amounts = _resolve_period_target_amounts_by_code(departments=departments, period=period)

    month_progress_cards = []
    period_progress_cards = []
    for current_department in departments:
        month_totals = month_totals_by_code.get(current_department.code, {})
        period_totals = period_totals_by_code.get(current_department.code, {})
        month_progress_cards.append(
            _build_progress_card(
                label=current_department.code,
                actual_amount=int(month_totals.get("support_amount") or 0)
                + int(month_totals.get("return_postal_amount") or 0)
                + int(month_totals.get("return_qr_amount") or 0),
                target_amount=int(month_target_amounts.get(current_department.code) or 0),
                summary_text=f"{target_month:%Y/%m} の補正込み累計",
                base_actual_amount=max(
                    (
                        int(month_totals.get("support_amount") or 0)
                        + int(month_totals.get("return_postal_amount") or 0)
                        + int(month_totals.get("return_qr_amount") or 0)
                    )
                    - int(month_adjustment_amounts.get(current_department.code) or 0),
                    0,
                ),
                adjustment_amount=int(month_adjustment_amounts.get(current_department.code) or 0),
            )
        )
        period_progress_cards.append(
            _build_progress_card(
                label=current_department.code,
                actual_amount=int(period_totals.get("support_amount") or 0)
                + int(period_totals.get("return_postal_amount") or 0)
                + int(period_totals.get("return_qr_amount") or 0),
                target_amount=int(period_target_amounts.get(current_department.code) or 0),
                summary_text=period.name if period else "路程未設定",
                base_actual_amount=max(
                    (
                        int(period_totals.get("support_amount") or 0)
                        + int(period_totals.get("return_postal_amount") or 0)
                        + int(period_totals.get("return_qr_amount") or 0)
                    )
                    - int(period_adjustment_amounts.get(current_department.code) or 0),
                    0,
                ),
                adjustment_amount=int(period_adjustment_amounts.get(current_department.code) or 0),
            )
        )

    return {
        "today": today,
        "overall_activity_trend": _build_overall_activity_trend(department=department),
        "activity_in_progress": _build_activity_member_rows(activity_in_progress),
        "activity_finished": _build_activity_member_rows(activity_finished),
        "active_member_cards": _build_active_member_cards(
            members=active_members,
            today=today,
            target_month=target_month,
            target_period=period,
            selected_department=department,
        ),
        "month_progress_cards": month_progress_cards,
        "period_progress_cards": period_progress_cards,
        "current_period": period,
    }


def _build_performance_history_snapshot(*, department, scope):
    target_codes = [department.code]
    scoped_totals_by_code = collect_department_final_actual_totals_by_codes(
        target_codes=target_codes,
        start_date=scope.start_date,
        end_date=scope.end_date,
        include_adjustments=True,
    )
    scoped_totals = scoped_totals_by_code.get(department.code, {})
    scoped_adjustment_amounts = _collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    month_progress_cards = []
    period_progress_cards = []
    if scope.scope == "month" and scope.month_start:
        month_target_amount = int(
            _resolve_month_target_amounts_by_code(
                departments=[department],
                target_month=scope.month_start,
            ).get(department.code)
            or 0
        )
        month_progress_cards.append(
            _build_progress_card(
                label=department.code,
                actual_amount=int(scoped_totals.get("support_amount") or 0)
                + int(scoped_totals.get("return_postal_amount") or 0)
                + int(scoped_totals.get("return_qr_amount") or 0),
                target_amount=month_target_amount,
                summary_text=f"{scope.month_start:%Y/%m} の補正込み累計",
                base_actual_amount=max(
                    (
                        int(scoped_totals.get("support_amount") or 0)
                        + int(scoped_totals.get("return_postal_amount") or 0)
                        + int(scoped_totals.get("return_qr_amount") or 0)
                    )
                    - int(scoped_adjustment_amounts.get(department.code) or 0),
                    0,
                ),
                adjustment_amount=int(scoped_adjustment_amounts.get(department.code) or 0),
            )
        )
    if scope.scope == "period" and scope.period:
        period_target_amount = int(
            _resolve_period_target_amounts_by_code(
                departments=[department],
                period=scope.period,
            ).get(department.code)
            or 0
        )
        period_progress_cards.append(
            _build_progress_card(
                label=department.code,
                actual_amount=int(scoped_totals.get("support_amount") or 0)
                + int(scoped_totals.get("return_postal_amount") or 0)
                + int(scoped_totals.get("return_qr_amount") or 0),
                target_amount=period_target_amount,
                summary_text=scope.period.name,
                base_actual_amount=max(
                    (
                        int(scoped_totals.get("support_amount") or 0)
                        + int(scoped_totals.get("return_postal_amount") or 0)
                        + int(scoped_totals.get("return_qr_amount") or 0)
                    )
                    - int(scoped_adjustment_amounts.get(department.code) or 0),
                    0,
                ),
                adjustment_amount=int(scoped_adjustment_amounts.get(department.code) or 0),
            )
        )

    active_members = list(
        Member.objects.active()
        .filter(department_links__department=department, department_links__department__is_active=True)
        .select_related("default_department")
        .distinct()
        .order_by("name", "id")
    )

    return {
        "scope": scope,
        "overall_activity_trend": _build_overall_activity_trend(
            department=department,
            start_date=scope.start_date,
            end_date=scope.end_date,
        ),
        "active_member_cards": _build_scoped_member_cards(
            members=active_members,
            selected_department=department,
            scope=scope,
        ),
        "month_progress_cards": month_progress_cards,
        "period_progress_cards": period_progress_cards,
    }


def _parse_selected_month(value, *, default):
    if not value:
        return default.replace(day=1)
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        return default.replace(day=1)


def _month_end(month_start):
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1) - timezone.timedelta(days=1)
    return date(month_start.year, month_start.month + 1, 1) - timezone.timedelta(days=1)


def _build_member_dashboard_entry_rows(*, member, department, month_start, month_end):
    member_entries = MemberDailyMetricEntry.objects.select_related("member", "department").prefetch_related("transactions").filter(
        member=member,
        department=department,
    )
    entries = list(member_entries.filter(entry_date__range=(month_start, month_end)).order_by("-entry_date", "-id"))
    adjustment_totals_map = _build_adjustment_totals_map(entries)
    entry_rows = []
    for entry in entries:
        adjustment_totals = adjustment_totals_map.get(
            (entry.member_id, entry.department_id, entry.entry_date),
            {
                "result_count": 0,
                "support_amount": 0,
                "return_postal_count": 0,
                "return_postal_amount": 0,
                "return_qr_count": 0,
                "return_qr_amount": 0,
                "cs_count": 0,
                "refugee_count": 0,
            },
        )
        entry_rows.append(
            {
                "entry": entry,
                "count_text": _count_text(entry, adjustment_totals),
                "amount_text": _amount_text(entry, adjustment_totals),
                "transactions": list(entry.transactions.all().order_by("created_at", "id")),
                "adjustment_summary": (
                    f"戻り 郵送 {adjustment_totals['return_postal_count']} / QR {adjustment_totals['return_qr_count']}"
                    if adjustment_totals["return_postal_count"] or adjustment_totals["return_qr_count"]
                    else ""
                ),
            }
        )
    return entry_rows


def _sum_adjustment_amount(*, member=None, department=None, start_date, end_date):
    queryset = MetricAdjustment.objects.filter(target_date__range=(start_date, end_date))
    if member is not None:
        queryset = queryset.filter(member=member)
    if department is not None:
        queryset = queryset.filter(department=department)
    totals = queryset.aggregate(
        support_amount_total=Sum("support_amount"),
        return_postal_amount_total=Sum("return_postal_amount"),
        return_qr_amount_total=Sum("return_qr_amount"),
    )
    return (
        int(totals["support_amount_total"] or 0)
        + int(totals["return_postal_amount_total"] or 0)
        + int(totals["return_qr_amount_total"] or 0)
    )


def _adjustment_totals_dict_from_queryset(*, queryset):
    totals = queryset.aggregate(
        result_count_total=Sum("result_count"),
        support_amount_total=Sum("support_amount"),
        return_postal_count_total=Sum("return_postal_count"),
        return_postal_amount_total=Sum("return_postal_amount"),
        return_qr_count_total=Sum("return_qr_count"),
        return_qr_amount_total=Sum("return_qr_amount"),
        cs_count_total=Sum("cs_count"),
        refugee_count_total=Sum("refugee_count"),
    )
    return {
        "result_count": int(totals["result_count_total"] or 0),
        "support_amount": int(totals["support_amount_total"] or 0),
        "return_postal_count": int(totals["return_postal_count_total"] or 0),
        "return_postal_amount": int(totals["return_postal_amount_total"] or 0),
        "return_qr_count": int(totals["return_qr_count_total"] or 0),
        "return_qr_amount": int(totals["return_qr_amount_total"] or 0),
        "cs_count": int(totals["cs_count_total"] or 0),
        "refugee_count": int(totals["refugee_count_total"] or 0),
    }


def _build_member_activity_trend(*, member, department, start_date=None, end_date=None):
    entry_queryset = MemberDailyMetricEntry.objects.select_related("department").filter(member=member, department=department)
    if start_date is not None and end_date is not None:
        entry_queryset = entry_queryset.filter(entry_date__range=(start_date, end_date))
        latest_entries = list(entry_queryset.order_by("entry_date", "id"))
    else:
        latest_entries = list(entry_queryset.order_by("-entry_date", "-id")[:120])
        latest_entries.reverse()
    if not latest_entries:
        return {
            "labels": [],
            "amounts": [],
            "counts": [],
            "has_data": False,
            "count_label": "件数",
            "default_visible_count": 0,
        }
    adjustment_totals_map = _build_adjustment_totals_map(latest_entries)
    labels = []
    amounts = []
    counts = []
    adjustment_amounts = []
    adjustment_counts = []
    approach_counts = []
    communication_counts = []
    target_amounts = []
    rate_values = []
    for entry in latest_entries:
        adjustment_totals = adjustment_totals_map.get(
            (entry.member_id, entry.department_id, entry.entry_date),
            {
                "result_count": 0,
                "support_amount": 0,
                "return_postal_count": 0,
                "return_postal_amount": 0,
                "return_qr_count": 0,
                "return_qr_amount": 0,
                "cs_count": 0,
                "refugee_count": 0,
            },
        )
        labels.append(entry.entry_date.strftime("%m/%d"))
        amount_value = _entry_final_amount_value(entry=entry, adjustment_totals=adjustment_totals)
        amounts.append(amount_value)
        adjustment_amount_value = (
            int(adjustment_totals["support_amount"])
            + int(adjustment_totals["return_postal_amount"])
            + int(adjustment_totals["return_qr_amount"])
        )
        adjustment_amounts.append(adjustment_amount_value)
        if department.code == "WV":
            adjustment_count_value = int(adjustment_totals["cs_count"]) + int(adjustment_totals["refugee_count"])
        else:
            adjustment_count_value = (
                int(adjustment_totals["result_count"])
                + int(adjustment_totals["return_postal_count"])
                + int(adjustment_totals["return_qr_count"])
            )
        counts.append(_entry_final_count_value(entry=entry, adjustment_totals=adjustment_totals))
        adjustment_counts.append(adjustment_count_value)
        approach_counts.append(int(entry.approach_count or 0))
        communication_counts.append(int(entry.communication_count or 0))
        target_amount = int(entry.daily_target_amount or 0)
        target_amounts.append(target_amount)
        rate_values.append(round((amount_value / target_amount) * 100, 1) if target_amount > 0 else None)
    return {
        "labels": labels,
        "amounts": amounts,
        "counts": counts,
        "adjustment_amounts": adjustment_amounts,
        "adjustment_counts": adjustment_counts,
        "approach_counts": approach_counts,
        "communication_counts": communication_counts,
        "target_amounts": target_amounts,
        "rate_values": rate_values,
        "has_data": True,
        "count_label": "件数" if department.code != "WV" else "件数相当",
        "default_visible_count": min(30, len(labels)),
    }


def _build_overall_activity_trend(*, department=None, start_date=None, end_date=None):
    entry_queryset = MemberDailyMetricEntry.objects.all()
    adjustment_queryset = MetricAdjustment.objects.all()
    if department is not None:
        entry_queryset = entry_queryset.filter(department=department)
        adjustment_queryset = adjustment_queryset.filter(department=department)
    if start_date is not None and end_date is not None:
        entry_queryset = entry_queryset.filter(entry_date__range=(start_date, end_date))
        adjustment_queryset = adjustment_queryset.filter(target_date__range=(start_date, end_date))
        latest_dates = list(entry_queryset.order_by("entry_date").values_list("entry_date", flat=True).distinct())
    else:
        latest_dates = list(entry_queryset.order_by("-entry_date").values_list("entry_date", flat=True).distinct()[:120])
        latest_dates.reverse()
    if not latest_dates:
        return {
            "labels": [],
            "amounts": [],
            "counts": [],
            "approach_counts": [],
            "communication_counts": [],
            "target_amounts": [],
            "rate_values": [],
            "has_data": False,
            "count_label": "件数",
            "default_visible_count": 0,
        }
    entry_totals = {
        row["entry_date"]: row
        for row in entry_queryset.filter(entry_date__in=latest_dates)
        .values("entry_date")
        .annotate(
            result_count_total=Sum("result_count"),
            support_amount_total=Sum("support_amount"),
            approach_count_total=Sum("approach_count"),
            communication_count_total=Sum("communication_count"),
            cs_count_total=Sum("cs_count"),
            refugee_count_total=Sum("refugee_count"),
        )
    }
    adjustment_totals = {
        row["target_date"]: row
        for row in adjustment_queryset.filter(target_date__in=latest_dates)
        .values("target_date")
        .annotate(
            result_count_total=Sum("result_count"),
            support_amount_total=Sum("support_amount"),
            return_postal_count_total=Sum("return_postal_count"),
            return_postal_amount_total=Sum("return_postal_amount"),
            return_qr_count_total=Sum("return_qr_count"),
            return_qr_amount_total=Sum("return_qr_amount"),
            cs_count_total=Sum("cs_count"),
            refugee_count_total=Sum("refugee_count"),
        )
    }
    summary_queryset = DepartmentDailyMetricSummary.objects.filter(entry_date__in=latest_dates)
    if department is not None:
        summary_queryset = summary_queryset.filter(department=department)
    daily_target_totals = {
        row["entry_date"]: int(row["daily_target_amount_total"] or 0)
        for row in summary_queryset
        .values("entry_date")
        .annotate(daily_target_amount_total=Sum("daily_target_amount"))
    }

    labels = []
    amounts = []
    counts = []
    approach_counts = []
    communication_counts = []
    target_amounts = []
    rate_values = []
    use_equivalent_count = department is None or department.code == "WV"
    for activity_date in latest_dates:
        entry_row = entry_totals.get(activity_date, {})
        adjustment_row = adjustment_totals.get(activity_date, {})
        labels.append(activity_date.strftime("%m/%d"))
        amount_value = (
            int(entry_row.get("support_amount_total") or 0)
            + int(adjustment_row.get("support_amount_total") or 0)
            + int(adjustment_row.get("return_postal_amount_total") or 0)
            + int(adjustment_row.get("return_qr_amount_total") or 0)
        )
        amounts.append(amount_value)
        if use_equivalent_count:
            counts.append(
                int(entry_row.get("result_count_total") or 0)
                + int(entry_row.get("cs_count_total") or 0)
                + int(entry_row.get("refugee_count_total") or 0)
                + int(adjustment_row.get("result_count_total") or 0)
                + int(adjustment_row.get("return_postal_count_total") or 0)
                + int(adjustment_row.get("return_qr_count_total") or 0)
                + int(adjustment_row.get("cs_count_total") or 0)
                + int(adjustment_row.get("refugee_count_total") or 0)
            )
        else:
            counts.append(
                int(entry_row.get("result_count_total") or 0)
                + int(adjustment_row.get("result_count_total") or 0)
                + int(adjustment_row.get("return_postal_count_total") or 0)
                + int(adjustment_row.get("return_qr_count_total") or 0)
            )
        approach_counts.append(int(entry_row.get("approach_count_total") or 0))
        communication_counts.append(int(entry_row.get("communication_count_total") or 0))
        target_amount = int(daily_target_totals.get(activity_date) or 0)
        target_amounts.append(target_amount)
        rate_values.append(round((amount_value / target_amount) * 100, 1) if target_amount > 0 else None)

    return {
        "labels": labels,
        "amounts": amounts,
        "counts": counts,
        "approach_counts": approach_counts,
        "communication_counts": communication_counts,
        "target_amounts": target_amounts,
        "rate_values": rate_values,
        "has_data": True,
        "count_label": "件数相当" if use_equivalent_count else "件数",
        "default_visible_count": min(30, len(labels)),
    }


def _build_member_dashboard_context(*, request, member, department, is_admin=False):
    today = timezone.localdate()
    selected_month = _parse_selected_month(request.GET.get("month"), default=today)
    selected_month_end = min(_month_end(selected_month), today)
    current_period = _resolve_current_period(today)
    recent_start = today - timedelta(days=29)
    recent_end = today
    entry_rows = _build_member_dashboard_entry_rows(
        member=member,
        department=department,
        month_start=selected_month,
        month_end=selected_month_end,
    )
    adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date__range=(selected_month, selected_month_end),
        ).order_by("-target_date", "-created_at")
    )
    recent_entry_rows = _build_member_dashboard_entry_rows(
        member=member,
        department=department,
        month_start=recent_start,
        month_end=recent_end,
    )
    recent_adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date__range=(recent_start, recent_end),
        ).order_by("-target_date", "-created_at")
    )
    activity_trend = _build_member_activity_trend(member=member, department=department)
    recent_totals = collect_member_final_actual_totals(
        member,
        department,
        recent_start,
        recent_end,
        include_adjustments=True,
    )
    recent_adjustment_queryset = MetricAdjustment.objects.filter(
        member=member,
        department=department,
        target_date__range=(recent_start, recent_end),
    )
    recent_adjustment_totals = _adjustment_totals_dict_from_queryset(queryset=recent_adjustment_queryset)
    recent_active_days = (
        MemberDailyMetricEntry.objects.filter(
            member=member,
            department=department,
            entry_date__range=(recent_start, recent_end),
        )
        .values("entry_date")
        .distinct()
        .count()
    )

    member_month_totals = collect_member_final_actual_totals(
        member,
        department,
        selected_month,
        selected_month_end,
        include_adjustments=True,
    )
    member_period_totals = collect_member_final_actual_totals(
        member,
        department,
        current_period.start_date if current_period else today,
        min(current_period.end_date, today) if current_period else today,
        include_adjustments=True,
    )
    department_month_totals = collect_department_final_actual_totals(
        department,
        selected_month,
        selected_month_end,
        include_adjustments=True,
    )
    department_period_totals = collect_department_final_actual_totals(
        department,
        current_period.start_date if current_period else today,
        min(current_period.end_date, today) if current_period else today,
        include_adjustments=True,
    )
    member_month_target = MemberMonthMetricTarget.objects.filter(
        member=member,
        department=department,
        target_month=selected_month,
    ).first()
    member_period_target = (
        MemberPeriodMetricTarget.objects.filter(
            member=member,
            department=department,
            period=current_period,
        ).first()
        if current_period
        else None
    )
    department_month_target_amount = int(
        _resolve_month_target_amounts_by_code(departments=[department], target_month=selected_month).get(department.code) or 0
    )
    department_period_target_amount = int(
        _resolve_period_target_amounts_by_code(departments=[department], period=current_period).get(department.code) or 0
    )
    department_month_actual_amount = (
        int(department_month_totals.get("support_amount") or 0)
        + int(department_month_totals.get("return_postal_amount") or 0)
        + int(department_month_totals.get("return_qr_amount") or 0)
    )
    department_period_actual_amount = (
        int(department_period_totals.get("support_amount") or 0)
        + int(department_period_totals.get("return_postal_amount") or 0)
        + int(department_period_totals.get("return_qr_amount") or 0)
    )
    member_month_actual_amount = (
        int(member_month_totals.get("support_amount") or 0)
        + int(member_month_totals.get("return_postal_amount") or 0)
        + int(member_month_totals.get("return_qr_amount") or 0)
    )
    member_period_actual_amount = (
        int(member_period_totals.get("support_amount") or 0)
        + int(member_period_totals.get("return_postal_amount") or 0)
        + int(member_period_totals.get("return_qr_amount") or 0)
    )
    edit_month_target = request.GET.get("edit_month_target") == "1"
    edit_period_target = request.GET.get("edit_period_target") == "1"

    department_month_progress = _build_progress_card(
        label="全体の月目標",
        actual_amount=department_month_actual_amount,
        target_amount=department_month_target_amount,
        summary_text=f"{department.code} 全体の{selected_month:%Y/%m}進捗",
        base_actual_amount=int(department_month_totals.get("support_amount") or 0),
        adjustment_amount=(
            int(department_month_totals.get("return_postal_amount") or 0)
            + int(department_month_totals.get("return_qr_amount") or 0)
        ),
    )
    department_month_progress["contribution"] = _build_contribution_summary(
        member_actual_amount=member_month_actual_amount,
        department_actual_amount=department_month_actual_amount,
    )
    department_period_progress = _build_progress_card(
        label="全体の路程目標",
        actual_amount=department_period_actual_amount,
        target_amount=department_period_target_amount,
        summary_text=f"{department.code} 全体の現在路程進捗",
        base_actual_amount=int(department_period_totals.get("support_amount") or 0),
        adjustment_amount=(
            int(department_period_totals.get("return_postal_amount") or 0)
            + int(department_period_totals.get("return_qr_amount") or 0)
        ),
    )
    department_period_progress["contribution"] = _build_contribution_summary(
        member_actual_amount=member_period_actual_amount,
        department_actual_amount=department_period_actual_amount,
    )

    return {
        "nav_items": _performance_member_nav_items(is_admin=is_admin),
        "member": member,
        "department": department,
        "month_label": selected_month.strftime("%Y/%m"),
        "period_label": current_period.name if current_period else "路程未設定",
        "selected_month": selected_month,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "recent_entry_rows": recent_entry_rows,
        "recent_adjustment_rows": recent_adjustment_rows,
        "recent_range_label": f"{recent_start:%Y/%m/%d} - {recent_end:%Y/%m/%d}",
        "recent_summary_items": [
            {"key": "approach_total", "label": "合計AP", "value": f"{int(recent_totals.get('approach_count') or 0):,}"},
            {"key": "communication_total", "label": "合計CM", "value": f"{int(recent_totals.get('communication_count') or 0):,}"},
            {"key": "count_total", "label": "合計件数", "value": _final_count_text(department_code=department.code, totals=recent_totals)},
            {"key": "amount_total", "label": "合計金額", "value": _final_amount_text(totals=recent_totals)},
            {
                "key": "adjustment_count_total",
                "label": "補正実績件数",
                "value": _final_count_text(department_code=department.code, totals=recent_adjustment_totals),
            },
            {
                "key": "adjustment_amount_total",
                "label": "補正実績金額",
                "value": _final_amount_text(totals=recent_adjustment_totals),
            },
            {"key": "active_days", "label": "稼働日数", "value": f"{recent_active_days:,}日"},
        ],
        "activity_trend": activity_trend,
        "department_month_progress": department_month_progress,
        "department_period_progress": department_period_progress,
        "member_month_progress": _build_progress_card(
            label="個人の月目標",
            actual_amount=member_month_actual_amount,
            target_amount=int(member_month_target.target_amount if member_month_target else 0),
            summary_text=f"{member.name} さんの{selected_month:%Y/%m}進捗",
            base_actual_amount=int(member_month_totals.get("support_amount") or 0),
            adjustment_amount=(
                int(member_month_totals.get("return_postal_amount") or 0)
                + int(member_month_totals.get("return_qr_amount") or 0)
            ),
        ),
        "member_period_progress": _build_progress_card(
            label="個人の路程目標",
            actual_amount=member_period_actual_amount,
            target_amount=int(member_period_target.target_amount if member_period_target else 0),
            summary_text=f"{member.name} さんの現在路程進捗",
            base_actual_amount=int(member_period_totals.get("support_amount") or 0),
            adjustment_amount=(
                int(member_period_totals.get("return_postal_amount") or 0)
                + int(member_period_totals.get("return_qr_amount") or 0)
            ),
        ),
        "month_target_form": MemberScopeTargetForm(
            member=member,
            scope="month",
            department=department,
            target_month=selected_month,
        ),
        "member_month_target": member_month_target,
        "period_target_form": MemberScopeTargetForm(
            member=member,
            scope="period",
            department=department,
            period=current_period,
        ) if current_period else None,
        "member_period_target": member_period_target,
        "edit_month_target": edit_month_target,
        "edit_period_target": edit_period_target,
        "is_admin_view": is_admin,
        "readonly_member_view": False,
    }


def _build_member_history_context(*, request, member, department, is_admin=False):
    today = timezone.localdate()
    dashboard_scope = request.GET.get("dashboard_scope") or "month"
    if dashboard_scope not in {"month", "period", "range"}:
        dashboard_scope = "month"
    dashboard_month = _parse_selected_month(request.GET.get("dashboard_month"), default=today)
    dashboard_period = None
    dashboard_period_id = request.GET.get("dashboard_period")
    if dashboard_period_id:
        dashboard_period = Period.objects.filter(pk=dashboard_period_id).first()
    if dashboard_period is None:
        dashboard_period = _resolve_current_period(today)
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

    entry_rows = _build_member_dashboard_entry_rows(
        member=member,
        department=department,
        month_start=scope.start_date,
        month_end=scope.end_date,
    )
    adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date__range=(scope.start_date, scope.end_date),
        ).order_by("-target_date", "-created_at")
    )
    activity_trend = _build_member_activity_trend(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    department_scope_totals = collect_department_final_actual_totals(
        department,
        scope.start_date,
        scope.end_date,
        include_adjustments=True,
    )
    member_scope_totals = collect_member_final_actual_totals(
        member,
        department,
        scope.start_date,
        scope.end_date,
        include_adjustments=True,
    )
    department_adjustment_amount = _sum_adjustment_amount(
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    member_adjustment_amount = _sum_adjustment_amount(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    department_actual_amount = (
        int(department_scope_totals.get("support_amount") or 0)
        + int(department_scope_totals.get("return_postal_amount") or 0)
        + int(department_scope_totals.get("return_qr_amount") or 0)
    )
    member_actual_amount = (
        int(member_scope_totals.get("support_amount") or 0)
        + int(member_scope_totals.get("return_postal_amount") or 0)
        + int(member_scope_totals.get("return_qr_amount") or 0)
    )

    department_progress_cards = []
    member_progress_cards = []
    if scope.scope == "month" and scope.month_start:
        department_target_amount = int(
            _resolve_month_target_amounts_by_code(
                departments=[department],
                target_month=scope.month_start,
            ).get(department.code)
            or 0
        )
        member_target = MemberMonthMetricTarget.objects.filter(
            member=member,
            department=department,
            target_month=scope.month_start,
        ).first()
        department_card = _build_progress_card(
            label="全体の月目標",
            actual_amount=department_actual_amount,
            target_amount=department_target_amount,
            summary_text=f"{department.code} 全体の{scope.month_start:%Y/%m}進捗",
            base_actual_amount=max(department_actual_amount - department_adjustment_amount, 0),
            adjustment_amount=department_adjustment_amount,
        )
        department_card["contribution"] = _build_contribution_summary(
            member_actual_amount=member_actual_amount,
            department_actual_amount=department_actual_amount,
        )
        department_progress_cards.append(department_card)
        member_progress_cards.append(
            _build_progress_card(
                label="個人の月目標",
                actual_amount=member_actual_amount,
                target_amount=int(member_target.target_amount if member_target else 0),
                summary_text=f"{member.name} さんの{scope.month_start:%Y/%m}進捗",
                base_actual_amount=max(member_actual_amount - member_adjustment_amount, 0),
                adjustment_amount=member_adjustment_amount,
            )
        )
    elif scope.scope == "period" and scope.period:
        department_target_amount = int(
            _resolve_period_target_amounts_by_code(
                departments=[department],
                period=scope.period,
            ).get(department.code)
            or 0
        )
        member_target = MemberPeriodMetricTarget.objects.filter(
            member=member,
            department=department,
            period=scope.period,
        ).first()
        department_card = _build_progress_card(
            label="全体の路程目標",
            actual_amount=department_actual_amount,
            target_amount=department_target_amount,
            summary_text=f"{department.code} 全体の{scope.period.name}進捗",
            base_actual_amount=max(department_actual_amount - department_adjustment_amount, 0),
            adjustment_amount=department_adjustment_amount,
        )
        department_card["contribution"] = _build_contribution_summary(
            member_actual_amount=member_actual_amount,
            department_actual_amount=department_actual_amount,
        )
        department_progress_cards.append(department_card)
        member_progress_cards.append(
            _build_progress_card(
                label="個人の路程目標",
                actual_amount=member_actual_amount,
                target_amount=int(member_target.target_amount if member_target else 0),
                summary_text=f"{member.name} さんの{scope.period.name}進捗",
                base_actual_amount=max(member_actual_amount - member_adjustment_amount, 0),
                adjustment_amount=member_adjustment_amount,
            )
        )

    return {
        "nav_items": _performance_member_nav_items(is_admin=is_admin),
        "member": member,
        "department": department,
        "is_admin_view": is_admin,
        "readonly_member_view": False,
        "dashboard_scope": dashboard_scope,
        "dashboard_month": dashboard_month,
        "dashboard_period": dashboard_period,
        "dashboard_periods": Period.objects.order_by("-end_date", "-start_date", "-id")[:24],
        "dashboard_start": dashboard_start,
        "dashboard_end": dashboard_end,
        "history_scope": scope,
        "activity_trend": activity_trend,
        "department_progress_cards": department_progress_cards,
        "member_progress_cards": member_progress_cards,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
    }


@require_performance_roles(ROLE_ADMIN)
def performance_index(request: HttpRequest) -> HttpResponse:
    filter_data = request.GET.copy()
    if not filter_data:
        filter_data["date_from"] = ""
        filter_data["date_to"] = ""
    filter_form = PerformanceEntryFilterForm(filter_data)
    entries_queryset = MemberDailyMetricEntry.objects.none()
    adjustments_preview = MetricAdjustment.objects.none()
    if filter_form.is_valid():
        entries_queryset = _filtered_entries_queryset(filter_form.cleaned_data)
        adjustments_preview = _filtered_adjustments_queryset(filter_form.cleaned_data)[:10]

    paginator = Paginator(entries_queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    entries = list(page_obj.object_list)
    adjustment_totals_map = _build_adjustment_totals_map(entries)
    entry_rows = []
    for entry in entries:
        key = (entry.member_id, entry.department_id, entry.entry_date)
        adjustment_totals = adjustment_totals_map.get(
            key,
            {
                "result_count": 0,
                "support_amount": 0,
                "return_postal_count": 0,
                "return_postal_amount": 0,
                "return_qr_count": 0,
                "return_qr_amount": 0,
                "cs_count": 0,
                "refugee_count": 0,
            },
        )
        entry_rows.append(
            {
                "entry": entry,
                "count_text": _count_text(entry, adjustment_totals),
                "amount_text": _amount_text(entry, adjustment_totals),
                "has_adjustments": any(adjustment_totals.values()),
                "adjustment_summary": (
                    f"戻り 郵送 {adjustment_totals['return_postal_count']} / QR {adjustment_totals['return_qr_count']}"
                    if adjustment_totals["return_postal_count"] or adjustment_totals["return_qr_count"]
                    else ""
                ),
            }
        )

    current_query = request.GET.copy()
    current_query.pop("page", None)
    department_id = request.GET.get("dashboard_department")
    dashboard_department = None
    if department_id:
        dashboard_department = Department.objects.filter(pk=department_id, is_active=True).first()
    if dashboard_department is None:
        dashboard_department = _resolve_default_dashboard_department()
    dashboard_month = timezone.localdate().replace(day=1)
    dashboard_period = _resolve_current_period(timezone.localdate())
    dashboard_start = request.GET.get("dashboard_start") or ""
    dashboard_end = request.GET.get("dashboard_end") or ""
    dashboard_snapshot = _build_performance_dashboard_snapshot(
        department=dashboard_department,
        target_month=dashboard_month,
        period=dashboard_period,
    )
    context = {
        "nav_items": _performance_nav_items(),
        "filter_form": filter_form,
        "page_obj": page_obj,
        "paginator": paginator,
        "entry_rows": entry_rows,
        "adjustments_preview": adjustments_preview,
        "current_query_string": current_query.urlencode(),
        "dashboard_snapshot": dashboard_snapshot,
        "dashboard_departments": Department.objects.filter(is_active=True).order_by("code", "id"),
        "dashboard_department": dashboard_department,
        "dashboard_month": dashboard_month,
        "dashboard_period": dashboard_period,
        "dashboard_periods": Period.objects.order_by("-end_date", "-start_date", "-id")[:24],
        "dashboard_scope": "month",
        "dashboard_start": dashboard_start,
        "dashboard_end": dashboard_end,
    }
    return render(request, "performance/index.html", context)


@require_performance_roles(ROLE_ADMIN)
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
        dashboard_department = _resolve_default_dashboard_department()
    dashboard_month = _parse_selected_month(request.GET.get("dashboard_month"), default=today)
    dashboard_period = None
    dashboard_period_id = request.GET.get("dashboard_period")
    if dashboard_period_id:
        dashboard_period = Period.objects.filter(pk=dashboard_period_id).first()
    if dashboard_period is None:
        dashboard_period = _resolve_current_period(today)
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
    history_snapshot = _build_performance_history_snapshot(
        department=dashboard_department,
        scope=scope,
    )
    context = {
        "nav_items": _performance_nav_items(),
        "dashboard_departments": Department.objects.filter(is_active=True).order_by("code", "id"),
        "dashboard_department": dashboard_department,
        "dashboard_month": dashboard_month,
        "dashboard_period": dashboard_period,
        "dashboard_periods": Period.objects.order_by("-end_date", "-start_date", "-id")[:24],
        "dashboard_scope": dashboard_scope,
        "dashboard_start": dashboard_start,
        "dashboard_end": dashboard_end,
        "history_snapshot": history_snapshot,
    }
    return render(request, "performance/history.html", context)


@require_performance_roles(ROLE_ADMIN)
def performance_entry_edit(request: HttpRequest, entry_id: int) -> HttpResponse:
    entry = get_object_or_404(MemberDailyMetricEntry.objects.select_related("member", "department"), pk=entry_id)
    status_message = ""
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
            return redirect(f"{reverse('performance_index')}?updated=entry")
        status_message = "入力内容を確認してください。"
    else:
        form = PerformanceMemberDailyMetricEntryForm(instance=entry)

    context = {
        "nav_items": _performance_nav_items(),
        "form": form,
        "entry": entry,
        "status_message": status_message,
    }
    return render(request, "performance/entry_edit.html", context)


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
    context = _build_member_dashboard_context(request=request, member=member, department=department, is_admin=True)
    return render(request, "performance/member_detail.html", context)


@require_performance_roles(ROLE_ADMIN)
def performance_member_history_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    context = _build_member_history_context(request=request, member=member, department=department, is_admin=True)
    return render(request, "performance/member_history.html", context)


@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_insight(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    context = _build_member_dashboard_context(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
    )
    context["readonly_member_view"] = True
    return render(request, "performance/member_detail.html", context)


@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history_insight(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    context = _build_member_history_context(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
    )
    context["readonly_member_view"] = True
    return render(request, "performance/member_history.html", context)


@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_dashboard(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        return redirect("performance_index")
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = _resolve_member_card_department(member=member)
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
    context = _build_member_dashboard_context(request=request, member=member, department=department, is_admin=False)
    return render(request, "performance/member_detail.html", context)


@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        return redirect("performance_index")
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = _resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    context = _build_member_history_context(request=request, member=member, department=department, is_admin=False)
    return render(request, "performance/member_history.html", context)


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
        adjustments_queryset = _filtered_adjustments_queryset(filter_form.cleaned_data)

    if request.method == "POST":
        adjustment_id = request.POST.get("adjustment_id")
        edit_adjustment = get_object_or_404(MetricAdjustment, pk=adjustment_id) if adjustment_id else None
        form = PerformanceMetricAdjustmentForm(request.POST, instance=edit_adjustment)
        if form.is_valid():
            adjustment = form.save(commit=False)
            if adjustment.created_by_id is None:
                adjustment.created_by = request.user
            adjustment.save()
            return redirect(f"{reverse('performance_adjustments')}?saved=1")
        status_message = "入力内容を確認してください。"
    else:
        form = PerformanceMetricAdjustmentForm(instance=edit_adjustment)
        if request.GET.get("saved") == "1":
            status_message = "補正実績を保存しました。"

    paginator = Paginator(adjustments_queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    member_options = {}
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
                {"id": member.id, "name": member.name}
            )
    context = {
        "nav_items": _performance_nav_items(),
        "filter_form": filter_form,
        "form": form,
        "edit_adjustment": edit_adjustment,
        "status_message": status_message,
        "page_obj": page_obj,
        "paginator": paginator,
        "adjustments": page_obj.object_list,
        "member_options": member_options,
    }
    return render(request, "performance/adjustments.html", context)


@require_performance_roles(ROLE_ADMIN)
def performance_adjustment_delete(request: HttpRequest, adjustment_id: int) -> HttpResponse:
    adjustment = get_object_or_404(MetricAdjustment, pk=adjustment_id)
    if request.method == "POST":
        adjustment.delete()
    return redirect(reverse("performance_adjustments"))
