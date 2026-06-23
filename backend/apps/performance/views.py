from functools import wraps
from dataclasses import dataclass
from datetime import date, timedelta

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
from apps.common.target_periods import current_active_period, period_options_active_first
from apps.dairymetrics.forms import DairyMetricsLoginForm, DairymetricsV2TransactionForm, MemberScopeTargetForm
from apps.dairymetrics.models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
    WVMetricCancellation,
)
from apps.mail.models import MailSendHistory
from apps.mail.services import send_member_direct_mail
from apps.dairymetrics.services.activity_state import auto_close_stale_entries
from apps.dairymetrics.services.final_actuals import (
    collect_department_final_actual_totals,
    collect_department_final_actual_totals_by_codes,
    collect_member_final_actual_totals,
    collect_member_final_actual_totals_by_ids,
)
from apps.performance.services.progress import (
    adjustment_totals_dict_from_queryset,
    build_contribution_summary,
    build_progress_card,
    collect_adjustment_amounts_by_codes,
    month_end,
    resolve_month_target_amounts_by_code,
    resolve_period_target_amounts_by_code,
    sum_adjustment_amount,
)
from apps.performance.services.member_details import (
    attach_transaction_edit_urls,
    build_entry_adjustment_detail_payload,
    build_member_dashboard_entry_rows,
    build_trend_date_links,
)
from apps.performance.services.admin_entries import build_admin_entry_management_page
from apps.performance.services.past_entries import (
    create_past_entry_with_transactions,
    normalize_transaction_payloads,
    parse_transactions_payload,
    transaction_preview_rows,
)
from apps.performance.services.trends import (
    EMPTY_ADJUSTMENT_TOTALS,
    build_adjustment_totals_map,
    build_member_activity_trend,
    build_overall_activity_trend,
    entry_final_amount_value,
    entry_final_count_value,
)
from apps.targets.models import (
    Period,
)

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


def _performance_next_url(next_url: str, *, fallback: str) -> str:
    if next_url and isinstance(next_url, str) and next_url.startswith("/performance/"):
        return next_url
    return fallback


def _can_edit_member_performance(*, is_admin: bool, readonly_member_view: bool) -> bool:
    return bool(is_admin or not readonly_member_view)


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
            auto_close_stale_entries()
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def _performance_nav_items():
    return [
        ("performance_index", "実績管理ダッシュボード"),
        ("performance_history", "過去の実績を見る"),
        ("performance_admin_entries", "全体エントリー管理"),
        ("performance_past_entry_create", "過去実績入力"),
        ("performance_adjustments", "戻り・増額登録"),
        ("testimony_article_list", "証を見る"),
        ("dashboard_index", "総合管理者ページ"),
    ]


def _performance_member_nav_items(*, is_admin=False):
    if is_admin:
        return [
            ("performance_index", "実績管理ダッシュボード"),
            ("performance_history", "過去の実績を見る"),
            ("testimony_article_list", "証を見る"),
        ]
    return [
        ("performance_member_dashboard", "実績管理ダッシュボード"),
        ("performance_index", "全体実績"),
        ("performance_member_history", "過去の実績を見る"),
        ("testimony_article_list", "証を見る"),
    ]


def _performance_member_page_nav_links(*, member, department, is_admin=False, readonly_member_view=False):
    links = []
    if is_admin:
        links.append(
            {
                "href": reverse("performance_index"),
                "label": "管理者用ダッシュボード",
            }
        )
    if readonly_member_view:
        links.extend(
            [
                {
                    "href": reverse("performance_member_insight", args=[member.id, department.id]),
                    "label": "実績管理ダッシュボード",
                },
                {
                    "href": reverse("performance_member_history_insight", args=[member.id, department.id]),
                    "label": "過去の実績を見る",
                },
                {
                    "href": reverse("testimony_article_list"),
                    "label": "証を見る",
                },
            ]
        )
        return links
    if is_admin:
        links.extend(
            [
                {
                    "href": reverse("performance_member_detail", args=[member.id, department.id]),
                    "label": "実績管理ダッシュボード",
                },
                {
                    "href": reverse("performance_member_history_detail", args=[member.id, department.id]),
                    "label": "過去の実績を見る",
                },
                {
                    "href": reverse("testimony_article_list"),
                    "label": "証を見る",
                },
            ]
        )
        return links
    return [
        {
            "href": reverse("performance_member_dashboard"),
            "label": "実績管理ダッシュボード",
        },
        {
            "href": reverse("performance_index"),
            "label": "全体実績",
        },
        {
            "href": reverse("performance_member_history"),
            "label": "過去の実績を見る",
        },
        {
            "href": reverse("testimony_article_list"),
            "label": "証を見る",
        },
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


def _filtered_adjustments_queryset(cleaned_data):
    queryset = MetricAdjustment.objects.select_related("member", "department", "created_by").order_by("-target_date", "-created_at")
    department = cleaned_data.get("department")
    member = cleaned_data.get("member")
    date_from = cleaned_data.get("date_from")
    date_to = cleaned_data.get("date_to")
    query = (cleaned_data.get("q") or "").strip()
    if department:
        queryset = queryset.filter(department=department)
    if member:
        queryset = queryset.filter(member=member)
    if date_from:
        queryset = queryset.filter(target_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(target_date__lte=date_to)
    if query:
        queryset = queryset.filter(
            Q(member__name__icontains=query)
            | Q(location_name__icontains=query)
            | Q(source_type__icontains=query)
            | Q(department__code__icontains=query)
        )
    return queryset


def _filtered_adjustments_list_queryset(cleaned_data):
    queryset = MetricAdjustment.objects.select_related("member", "department", "created_by").order_by("-target_date", "-created_at")
    department = cleaned_data.get("department")
    query = (cleaned_data.get("q") or "").strip()
    if department:
        queryset = queryset.filter(department=department)
    if query:
        queryset = queryset.filter(
            Q(member__name__icontains=query)
            | Q(location_name__icontains=query)
            | Q(source_type__icontains=query)
            | Q(department__code__icontains=query)
        )
    return queryset


def _filtered_cancellations_list_queryset(cleaned_data):
    queryset = WVMetricCancellation.objects.select_related("member", "department", "created_by").order_by("-target_date", "-created_at")
    department = cleaned_data.get("department")
    query = (cleaned_data.get("q") or "").strip()
    if department:
        queryset = queryset.filter(department=department)
    if query:
        queryset = queryset.filter(
            Q(member__name__icontains=query)
            | Q(location_name__icontains=query)
            | Q(comment__icontains=query)
            | Q(department__code__icontains=query)
        )
        if query in "キャンセル":
            queryset = WVMetricCancellation.objects.select_related("member", "department", "created_by").order_by(
                "-target_date",
                "-created_at",
            )
            if department:
                queryset = queryset.filter(department=department)
    return queryset


def _adjustment_list_row(adjustment):
    if adjustment.department.code == "WV":
        amount = adjustment.support_amount
        detail_text = f"CS {adjustment.cs_count} / 難民 {adjustment.refugee_count}"
    elif adjustment.source_type == MetricAdjustment.SOURCE_POSTAL:
        amount = adjustment.return_postal_amount
        detail_text = "郵送"
    elif adjustment.source_type == MetricAdjustment.SOURCE_QR:
        amount = adjustment.return_qr_amount
        detail_text = "QR"
    else:
        amount = adjustment.support_amount
        detail_text = adjustment.get_source_type_display()
    return {
        "id": adjustment.id,
        "record_type": "adjustment",
        "target_date": adjustment.target_date,
        "created_at": adjustment.created_at,
        "member_name": adjustment.member.name,
        "department_code": adjustment.department.code,
        "source_label": adjustment.get_source_type_display(),
        "location_name": adjustment.location_name,
        "detail_text": detail_text,
        "amount": amount,
        "edit_url": f"{reverse('performance_adjustments')}?edit={adjustment.id}",
        "delete_url": reverse("performance_adjustment_delete", args=[adjustment.id]),
    }


def _cancellation_list_row(cancellation):
    return {
        "id": cancellation.id,
        "record_type": "cancellation",
        "target_date": cancellation.target_date,
        "created_at": cancellation.created_at,
        "member_name": cancellation.member.name,
        "department_code": cancellation.department.code,
        "source_label": "キャンセル",
        "location_name": cancellation.location_name,
        "detail_text": f"CS {cancellation.cs_count} / 難民 {cancellation.refugee_count}",
        "amount": cancellation.support_amount,
        "edit_url": "",
        "delete_url": reverse("performance_cancellation_delete", args=[cancellation.id]),
    }


def _combined_adjustment_list_rows(cleaned_data):
    rows = [_adjustment_list_row(adjustment) for adjustment in _filtered_adjustments_list_queryset(cleaned_data)]
    rows.extend(_cancellation_list_row(cancellation) for cancellation in _filtered_cancellations_list_queryset(cleaned_data))
    return sorted(rows, key=lambda row: (row["target_date"], row["created_at"]), reverse=True)


def _count_text(entry, adjustment_totals):
    if entry.department.code == "WV":
        total_cs = int(entry.cs_count or 0) + int(adjustment_totals["cs_count"])
        total_refugee = int(entry.refugee_count or 0) + int(adjustment_totals["refugee_count"])
        return f"{total_cs + total_refugee}件"
    total_count = entry_final_count_value(entry=entry, adjustment_totals=adjustment_totals)
    return f"{total_count}件"


def _wv_count_detail_text(*, cs_count: int, refugee_count: int) -> str:
    return f"(CS {int(cs_count or 0)}件 / 難民 {int(refugee_count or 0)}件)"


def _amount_text(entry, adjustment_totals):
    total_amount = entry_final_amount_value(entry=entry, adjustment_totals=adjustment_totals)
    return f"{total_amount:,}円"


def _field_count_text(entry):
    if entry.department.code == "WV":
        return f"CS {int(entry.cs_count or 0)} / 難民 {int(entry.refugee_count or 0)}"
    return f"{int(entry.result_count or 0)}件"


def _field_amount_text(entry):
    return f"{int(entry.support_amount or 0):,}円"


def _resolve_current_period(today):
    return current_active_period(target_date=today)


def _period_range_label(period):
    if period is None:
        return ""
    return f"{period.start_date:%Y/%m/%d} - {period.end_date:%Y/%m/%d}"


def _period_display_label(period):
    if period is None:
        return "路程未設定"
    return f"{period.name}（{_period_range_label(period)}）"


def _build_activity_member_rows(entries):
    rows = []
    for entry in entries:
        support_amount = int(entry.support_amount or 0)
        daily_target_amount = int(entry.daily_target_amount or 0)
        rows.append(
            {
                "entry_id": entry.id,
                "member_id": entry.member_id,
                "member_name": entry.member.name,
                "department_code": entry.department.code,
                "department_id": entry.department_id,
                "updated_at": timezone.localtime(entry.updated_at).strftime("%H:%M"),
                "location_name": (entry.location_name or "").strip(),
                "amount_text": f"{support_amount:,}円 / {daily_target_amount:,}円",
                "count_text": (
                    f"CS {int(entry.cs_count or 0)} / 難民 {int(entry.refugee_count or 0)}"
                    if entry.department.code == "WV"
                    else f"{int(entry.result_count or 0)}件"
                ),
                "has_email": bool(entry.member.email),
            }
        )
    return rows


def _resolve_member_department_pairs(*, members, selected_department):
    member_department_pairs = []
    for member in members:
        department = _resolve_member_card_department(member=member, selected_department=selected_department)
        if department is None:
            continue
        member_department_pairs.append((member, department))
    return member_department_pairs


def _collect_member_totals_by_department(*, member_department_pairs, start_date, end_date):
    totals_by_department = {}
    departments_by_id = {department.id: department for _, department in member_department_pairs}
    for department in departments_by_id.values():
        department_member_ids = [member.id for member, current_department in member_department_pairs if current_department.id == department.id]
        totals_by_department[department.id] = collect_member_final_actual_totals_by_ids(
            member_ids=department_member_ids,
            department=department,
            start_date=start_date,
            end_date=end_date,
            include_adjustments=True,
        )
    return totals_by_department


def _collect_member_latest_entries_by_department(*, member_department_pairs, start_date=None, end_date=None):
    latest_entries_by_department = {}
    adjustment_totals_by_department = {}
    departments_by_id = {department.id: department for _, department in member_department_pairs}
    for department in departments_by_id.values():
        department_member_ids = [member.id for member, current_department in member_department_pairs if current_department.id == department.id]
        entries_qs = MemberDailyMetricEntry.objects.filter(
            member_id__in=department_member_ids,
            department=department,
        )
        if start_date is not None and end_date is not None:
            entries_qs = entries_qs.filter(entry_date__range=(start_date, end_date))
        department_entries = list(
            entries_qs.select_related("member", "department").order_by("member_id", "-entry_date", "-id")
        )
        latest_entries_by_department[department.id] = {}
        picked_entries = []
        for entry in department_entries:
            pair_key = (entry.member_id, entry.department_id)
            bucket = latest_entries_by_department[department.id].setdefault(pair_key, [])
            if len(bucket) < 6:
                bucket.append(entry)
                picked_entries.append(entry)
        adjustment_totals_by_department[department.id] = build_adjustment_totals_map(picked_entries)
    return latest_entries_by_department, adjustment_totals_by_department


def _build_member_recent_metrics(*, entries, adjustment_totals_map, department_code):
    latest_final_counts = []
    closed_entries = [entry for entry in entries if entry.activity_closed][:3]
    for latest_entry in closed_entries:
        latest_totals = adjustment_totals_map.get(
            (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
            EMPTY_ADJUSTMENT_TOTALS,
        )
        latest_final_counts.append(entry_final_count_value(entry=latest_entry, adjustment_totals=latest_totals))

    zero_streak_warning = len(latest_final_counts) == 3 and all(count == 0 for count in latest_final_counts)
    active_streak_good = len(latest_final_counts) == 3 and all(count >= 1 for count in latest_final_counts)
    if not entries:
        return {
            "updated_at": "実績なし",
            "recent_date_text": "-",
            "recent_amount_text": "-",
            "recent_count_text": "-",
            "recent_count_subtext": "",
            "recent_sort_date": None,
            "zero_streak_warning": zero_streak_warning,
            "zero_streak_text": "3稼働連続0件" if zero_streak_warning else "",
            "active_streak_good": active_streak_good,
            "active_streak_text": "3稼働連続1件以上" if active_streak_good else "",
        }

    latest_entry = entries[0]
    latest_totals = adjustment_totals_map.get(
        (latest_entry.member_id, latest_entry.department_id, latest_entry.entry_date),
        EMPTY_ADJUSTMENT_TOTALS,
    )
    return {
        "updated_at": timezone.localtime(latest_entry.updated_at).strftime("%H:%M"),
        "recent_date_text": latest_entry.entry_date.strftime("%Y/%m/%d"),
        "recent_amount_text": _amount_text(latest_entry, latest_totals),
        "recent_count_text": _count_text(latest_entry, latest_totals),
        "recent_count_subtext": (
            _wv_count_detail_text(
                cs_count=int(latest_entry.cs_count or 0) + int(latest_totals["cs_count"]),
                refugee_count=int(latest_entry.refugee_count or 0) + int(latest_totals["refugee_count"]),
            )
            if department_code == "WV"
            else ""
        ),
        "recent_sort_date": latest_entry.entry_date,
        "zero_streak_warning": zero_streak_warning,
        "zero_streak_text": "3稼働連続0件" if zero_streak_warning else "",
        "active_streak_good": active_streak_good,
        "active_streak_text": "3稼働連続1件以上" if active_streak_good else "",
    }


def _build_scoped_member_cards(*, members, selected_department, scope):
    cards = []
    scope_metric_label = {
        "month": "月累計",
        "period": "路程累計",
        "range": "期間累計",
    }.get(scope.scope, "累計")
    member_department_pairs = _resolve_member_department_pairs(
        members=members,
        selected_department=selected_department,
    )
    department_totals_map = _collect_member_totals_by_department(
        member_department_pairs=member_department_pairs,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    latest_entries_by_pair, adjustment_totals_by_pair = _collect_member_latest_entries_by_department(
        member_department_pairs=member_department_pairs,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    for member, department in member_department_pairs:
        scoped_totals = department_totals_map.get(department.id, {}).get(member.id, {})
        scoped_entries = latest_entries_by_pair.get(department.id, {}).get((member.id, department.id), [])
        latest_adjustment_totals = adjustment_totals_by_pair.get(department.id, {})
        recent_metrics = _build_member_recent_metrics(
            entries=scoped_entries,
            adjustment_totals_map=latest_adjustment_totals,
            department_code=department.code,
        )
        cards.append(
            {
                "member_name": member.name,
                "department_code": department.code,
                "updated_at": recent_metrics["updated_at"],
                "scope_label": scope_metric_label,
                "scope_amount_text": _final_amount_text(totals=scoped_totals),
                "scope_count_text": _final_count_text(department_code=department.code, totals=scoped_totals),
                "scope_count_subtext": _final_count_subtext(department_code=department.code, totals=scoped_totals),
                "recent_date_text": recent_metrics["recent_date_text"],
                "recent_amount_text": recent_metrics["recent_amount_text"],
                "recent_count_text": recent_metrics["recent_count_text"],
                "recent_count_subtext": recent_metrics["recent_count_subtext"],
                "recent_sort_date": recent_metrics["recent_sort_date"],
                "zero_streak_warning": recent_metrics["zero_streak_warning"],
                "zero_streak_text": recent_metrics["zero_streak_text"],
                "active_streak_good": recent_metrics["active_streak_good"],
                "active_streak_text": recent_metrics["active_streak_text"],
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
        return f"{total_cs + total_refugee}件"
    total_count = (
        int(totals.get("result_count") or 0)
        + int(totals.get("return_postal_count") or 0)
        + int(totals.get("return_qr_count") or 0)
    )
    return f"{total_count}件"


def _final_count_subtext(*, department_code, totals):
    if department_code != "WV":
        return ""
    return _wv_count_detail_text(
        cs_count=int(totals.get("cs_count") or 0),
        refugee_count=int(totals.get("refugee_count") or 0),
    )


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


def _totals_count_text_for_dashboard(*, department, totals):
    if department is not None:
        return _final_count_text(department_code=department.code, totals=totals)
    total_count = (
        int(totals.get("result_count") or 0)
        + int(totals.get("return_postal_count") or 0)
        + int(totals.get("return_qr_count") or 0)
        + int(totals.get("cs_count") or 0)
        + int(totals.get("refugee_count") or 0)
    )
    return f"{total_count}件相当"


def _today_target_text_for_dashboard(*, department, count_target, amount_target):
    return f"{int(amount_target or 0):,}円"


def _today_rate_text_for_dashboard(*, actual_count, actual_amount, count_target, amount_target):
    amount_rate = None
    if amount_target and int(amount_target) > 0:
        amount_rate = round((int(actual_amount or 0) / int(amount_target)) * 100, 1)
    if amount_rate is not None:
        return f"{amount_rate}%"
    return "-"


def _resolve_member_card_department(*, member, selected_department=None):
    if selected_department is not None:
        return selected_department
    if member.default_department_id and member.default_department and member.default_department.is_active:
        return member.default_department
    prefetched_links = getattr(member, "_prefetched_objects_cache", {}).get("department_links")
    if prefetched_links is not None:
        active_departments = sorted(
            [
                link.department
                for link in prefetched_links
                if link.department and link.department.is_active
            ],
            key=lambda department: (department.code, department.id),
        )
        return active_departments[0] if active_departments else None
    return (
        Department.objects.filter(member_links__member=member, is_active=True)
        .order_by("code", "id")
        .first()
    )


def _members_for_history_scope(*, department, start_date, end_date):
    active_member_ids = set(
        Member.objects.active()
        .filter(department_links__department=department, department_links__department__is_active=True)
        .values_list("id", flat=True)
    )
    scoped_member_ids = set(
        MemberDailyMetricEntry.objects.filter(
            department=department,
            entry_date__range=(start_date, end_date),
        ).values_list("member_id", flat=True)
    )
    scoped_member_ids.update(
        MetricAdjustment.objects.filter(
            department=department,
            target_date__range=(start_date, end_date),
        ).values_list("member_id", flat=True)
    )
    member_ids = active_member_ids | scoped_member_ids
    if not member_ids:
        return []
    return list(
        Member.objects.filter(
            id__in=member_ids,
            department_links__department=department,
            department_links__department__is_active=True,
        )
        .select_related("default_department")
        .distinct()
        .order_by("name", "id")
    )


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


def _resolve_performance_history_scope(*, today, scope_value, requested_month=None, requested_period=None, requested_start=None, requested_end=None):
    if scope_value == "period" and requested_period is not None:
        return PerformanceHistoryScope(
            scope="period",
            label=_period_display_label(requested_period),
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
        end_date=min(month_end(month_start), today),
        month_start=month_start,
    )


def _build_active_member_cards(*, members, today, target_month, target_period, selected_department=None):
    cards = []
    member_department_pairs = _resolve_member_department_pairs(
        members=members,
        selected_department=selected_department,
    )
    month_totals_map = _collect_member_totals_by_department(
        member_department_pairs=member_department_pairs,
        start_date=target_month,
        end_date=today,
    )
    period_totals_map = _collect_member_totals_by_department(
        member_department_pairs=member_department_pairs,
        start_date=target_period.start_date if target_period else today,
        end_date=min(target_period.end_date, today) if target_period else today,
    )
    latest_entries_by_pair, adjustment_totals_by_pair = _collect_member_latest_entries_by_department(
        member_department_pairs=member_department_pairs,
    )

    for member, department in member_department_pairs:
        month_totals = month_totals_map.get(department.id, {}).get(member.id, {})
        period_totals = period_totals_map.get(department.id, {}).get(member.id, {})
        latest_entries = latest_entries_by_pair.get(department.id, {}).get((member.id, department.id), [])
        latest_adjustment_totals = adjustment_totals_by_pair.get(department.id, {})
        recent_metrics = _build_member_recent_metrics(
            entries=latest_entries,
            adjustment_totals_map=latest_adjustment_totals,
            department_code=department.code,
        )
        cards.append(
            {
                "member_name": member.name,
                "department_code": department.code,
                "updated_at": recent_metrics["updated_at"],
                "month_amount_text": _final_amount_text(totals=month_totals),
                "month_count_text": _final_count_text(department_code=department.code, totals=month_totals),
                "month_count_subtext": _final_count_subtext(department_code=department.code, totals=month_totals),
                "period_amount_text": _final_amount_text(totals=period_totals),
                "period_count_text": _final_count_text(department_code=department.code, totals=period_totals),
                "period_count_subtext": _final_count_subtext(department_code=department.code, totals=period_totals),
                "recent_date_text": recent_metrics["recent_date_text"],
                "recent_amount_text": recent_metrics["recent_amount_text"],
                "recent_count_text": recent_metrics["recent_count_text"],
                "recent_count_subtext": recent_metrics["recent_count_subtext"],
                "recent_sort_date": recent_metrics["recent_sort_date"],
                "zero_streak_warning": recent_metrics["zero_streak_warning"],
                "zero_streak_text": recent_metrics["zero_streak_text"],
                "active_streak_good": recent_metrics["active_streak_good"],
                "active_streak_text": recent_metrics["active_streak_text"],
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
    today_entry_totals = (
        collect_department_final_actual_totals(
            department,
            today,
            today,
            include_adjustments=False,
        )
        if department is not None
        else collect_department_final_actual_totals_by_codes(
            target_codes=[current_department.code for current_department in departments],
            start_date=today,
            end_date=today,
            include_adjustments=False,
        )
    )
    if department is None:
        merged_today_totals = {
            "result_count": 0,
            "support_amount": 0,
            "return_postal_count": 0,
            "return_postal_amount": 0,
            "return_qr_count": 0,
            "return_qr_amount": 0,
            "cs_count": 0,
            "refugee_count": 0,
            "approach_count": 0,
            "communication_count": 0,
        }
        for department_totals in today_entry_totals.values():
            for key in merged_today_totals:
                merged_today_totals[key] += int(department_totals.get(key) or 0)
        today_entry_totals = merged_today_totals
    summary_queryset = DepartmentDailyMetricSummary.objects.filter(entry_date=today)
    if department is not None:
        summary_queryset = summary_queryset.filter(department=department)
    elif departments:
        summary_queryset = summary_queryset.filter(department__in=departments)
    today_targets = summary_queryset.aggregate(
        total_count=Sum("daily_target_count"),
        total_amount=Sum("daily_target_amount"),
    )
    today_target_count = int(today_targets.get("total_count") or 0)
    today_target_amount = int(today_targets.get("total_amount") or 0)
    today_actual_count = _final_count_value(
        department_code=department.code if department is not None else "",
        totals=today_entry_totals,
    ) if department is not None else (
        int(today_entry_totals.get("result_count") or 0)
        + int(today_entry_totals.get("return_postal_count") or 0)
        + int(today_entry_totals.get("return_qr_count") or 0)
        + int(today_entry_totals.get("cs_count") or 0)
        + int(today_entry_totals.get("refugee_count") or 0)
    )
    today_actual_amount = (
        int(today_entry_totals.get("support_amount") or 0)
        + int(today_entry_totals.get("return_postal_amount") or 0)
        + int(today_entry_totals.get("return_qr_amount") or 0)
    )
    if department:
        active_members = list(
            Member.objects.active()
            .filter(department_links__department=department, department_links__department__is_active=True)
            .select_related("default_department")
            .prefetch_related("department_links__department")
            .distinct()
            .order_by("name", "id")
        )
    else:
        active_members = list(
            Member.objects.active()
            .filter(Q(default_department__is_active=True) | Q(department_links__department__is_active=True))
            .select_related("default_department")
            .prefetch_related("department_links__department")
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
    month_adjustment_amounts = collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=target_month,
        end_date=today,
    )
    period_adjustment_amounts = collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=period.start_date if period else today,
        end_date=min(period.end_date, today) if period else today,
    ) if target_codes else {}

    month_target_amounts = resolve_month_target_amounts_by_code(departments=departments, target_month=target_month)
    period_target_amounts = resolve_period_target_amounts_by_code(departments=departments, period=period)

    month_progress_cards = []
    period_progress_cards = []
    for current_department in departments:
        month_totals = month_totals_by_code.get(current_department.code, {})
        period_totals = period_totals_by_code.get(current_department.code, {})
        month_progress_cards.append(
            build_progress_card(
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
            build_progress_card(
                label=current_department.code,
                actual_amount=int(period_totals.get("support_amount") or 0)
                + int(period_totals.get("return_postal_amount") or 0)
                + int(period_totals.get("return_qr_amount") or 0),
                target_amount=int(period_target_amounts.get(current_department.code) or 0),
                summary_text=_period_display_label(period),
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
        "today_total_count_text": _totals_count_text_for_dashboard(department=department, totals=today_entry_totals),
        "today_total_count_subtext": (
            _final_count_subtext(department_code=department.code, totals=today_entry_totals)
            if department is not None
            else ""
        ),
        "today_total_amount_text": _final_amount_text(totals=today_entry_totals),
        "today_target_text": _today_target_text_for_dashboard(
            department=department,
            count_target=today_target_count,
            amount_target=today_target_amount,
        ),
        "today_rate_text": _today_rate_text_for_dashboard(
            actual_count=today_actual_count,
            actual_amount=today_actual_amount,
            count_target=today_target_count,
            amount_target=today_target_amount,
        ),
        "overall_activity_trend": build_overall_activity_trend(department=department),
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
        "current_period_display": _period_display_label(period),
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
    scoped_adjustment_amounts = collect_adjustment_amounts_by_codes(
        target_codes=target_codes,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    month_progress_cards = []
    period_progress_cards = []
    if scope.scope == "month" and scope.month_start:
        month_target_amount = int(
            resolve_month_target_amounts_by_code(
                departments=[department],
                target_month=scope.month_start,
            ).get(department.code)
            or 0
        )
        month_progress_cards.append(
            build_progress_card(
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
            resolve_period_target_amounts_by_code(
                departments=[department],
                period=scope.period,
            ).get(department.code)
            or 0
        )
        period_progress_cards.append(
            build_progress_card(
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

    active_members = _members_for_history_scope(
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )

    return {
        "scope": scope,
        "overall_activity_trend": build_overall_activity_trend(
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


def _department_today_transaction_detail_rows(*, department, target_date):
    transactions = (
        MemberMetricTransaction.objects.filter(
            entry__department=department,
            entry__entry_date=target_date,
        )
        .select_related("entry", "entry__member", "entry__department")
        .order_by("-entry__updated_at", "-id")
    )
    rows = []
    for tx in transactions:
        if department.code == "WV":
            if tx.wv_result_type == MemberMetricTransaction.WV_RESULT_CS:
                type_text = f"CS {int(tx.wv_cs_count or 0)}口"
            elif tx.wv_result_type == MemberMetricTransaction.WV_RESULT_REFUGEE:
                type_text = f"難民 {int(tx.wv_refugee_amount or 0):,}円"
            else:
                type_text = f"CS {int(tx.wv_cs_count or 0)}口 + 難民 {int(tx.wv_refugee_amount or 0):,}円"
        else:
            type_text = "1件"
        rows.append(
            {
                "id": tx.id,
                "member_name": tx.entry.member.name,
                "location_name": tx.location or tx.entry.location_name or "-",
                "amount_text": f"{int(tx.support_amount or 0):,}円",
                "type_text": type_text,
                "detail_text": f"{tx.get_age_band_display()} / {tx.get_gender_display()} / {tx.get_nationality_type_display()}",
                "comment": tx.comment,
                "edit_url": reverse("performance_transaction_edit", args=[tx.id]),
                "delete_url": reverse("performance_transaction_delete", args=[tx.id]),
            }
        )
    return rows


def _department_today_mail_detail_rows(*, department, target_date):
    histories = (
        MailSendHistory.objects.filter(
            department=department,
            activity_date=target_date,
            is_test=False,
            transaction__isnull=False,
        )
        .select_related("sender_member", "transaction", "transaction__entry", "recipient_group")
        .order_by("-created_at", "-id")
    )
    rows = []
    for history in histories:
        rows.append(
            {
                "member_name": history.transaction.entry.member.name if history.transaction and history.transaction.entry_id else "-",
                "subject": history.subject_snapshot,
                "status_text": history.get_status_display(),
                "status_value": history.status,
                "sent_at_text": timezone.localtime(history.sent_at).strftime("%Y/%m/%d %H:%M") if history.sent_at else "-",
                "recipient_text": history.sent_to_snapshot or "-",
                "body_text": history.body_snapshot,
                "error_text": history.error_message,
            }
        )
    return rows


def _build_department_today_detail_context(*, department, target_date, next_url=""):
    return {
        "today_detail_date": target_date,
        "today_detail_next_url": next_url,
        "today_transaction_rows": _department_today_transaction_detail_rows(
            department=department,
            target_date=target_date,
        ),
        "today_mail_rows": _department_today_mail_detail_rows(
            department=department,
            target_date=target_date,
        ),
    }


def _parse_selected_month(value, *, default):
    if not value:
        return default.replace(day=1)
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        return default.replace(day=1)


def _build_member_dashboard_context(*, request, member, department, is_admin=False):
    today = timezone.localdate()
    selected_month = _parse_selected_month(request.GET.get("month"), default=today)
    selectedmonth_end = min(month_end(selected_month), today)
    current_period = _resolve_current_period(today)
    recent_start = today - timedelta(days=29)
    recent_end = today
    entry_rows = build_member_dashboard_entry_rows(
        member=member,
        department=department,
        month_start=selected_month,
        month_end=selectedmonth_end,
        field_count_text=_field_count_text,
        field_amount_text=_field_amount_text,
    )
    adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date__range=(selected_month, selectedmonth_end),
        ).order_by("-target_date", "-created_at")
    )
    recent_detail_payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=recent_start,
        end_date=recent_end,
        limit=5,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=_field_count_text,
            field_amount_text=_field_amount_text,
            **kwargs,
        ),
    )
    activity_trend = build_member_activity_trend(member=member, department=department)
    detail_next_url = (
        reverse("performance_member_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_dashboard")
    )
    attach_transaction_edit_urls(entry_rows=recent_detail_payload["entry_rows"], next_url=detail_next_url)
    for row in recent_detail_payload["entry_rows"]:
        row["edit_url"] = (
            f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
            f"?{urlencode({'next': detail_next_url})}"
        )
        row["delete_url"] = (
            f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
            f"?{urlencode({'next': detail_next_url})}"
        )
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
    recent_adjustment_totals = adjustment_totals_dict_from_queryset(queryset=recent_adjustment_queryset)
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
        selectedmonth_end,
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
        selectedmonth_end,
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
        resolve_month_target_amounts_by_code(departments=[department], target_month=selected_month).get(department.code) or 0
    )
    department_period_target_amount = int(
        resolve_period_target_amounts_by_code(departments=[department], period=current_period).get(department.code) or 0
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

    department_month_progress = build_progress_card(
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
    department_month_progress["contribution"] = build_contribution_summary(
        member_actual_amount=member_month_actual_amount,
        department_actual_amount=department_month_actual_amount,
    )
    department_period_progress = build_progress_card(
        label="全体の路程目標",
        actual_amount=department_period_actual_amount,
        target_amount=department_period_target_amount,
        summary_text=f"{department.code} 全体の{_period_display_label(current_period)}進捗",
        base_actual_amount=int(department_period_totals.get("support_amount") or 0),
        adjustment_amount=(
            int(department_period_totals.get("return_postal_amount") or 0)
            + int(department_period_totals.get("return_qr_amount") or 0)
        ),
    )
    department_period_progress["contribution"] = build_contribution_summary(
        member_actual_amount=member_period_actual_amount,
        department_actual_amount=department_period_actual_amount,
    )

    return {
        "nav_items": _performance_member_page_nav_links(
            member=member,
            department=department,
            is_admin=is_admin,
        ),
        "member": member,
        "department": department,
        "month_label": selected_month.strftime("%Y/%m"),
        "period_label": current_period.name if current_period else "路程未設定",
        "period_range_label": _period_range_label(current_period),
        "selected_month": selected_month,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "recent_entry_rows": recent_detail_payload["entry_rows"],
        "recent_adjustment_rows": recent_detail_payload["adjustment_rows"],
        "recent_range_label": f"{recent_start:%Y/%m/%d} - {recent_end:%Y/%m/%d}",
        "recent_detail_start": recent_start,
        "recent_detail_end": recent_end,
        "recent_detail_limit": 5,
        "recent_detail_limit_step": 5,
        "recent_detail_selected_date": None,
        "recent_detail_has_more": recent_detail_payload["has_more"],
        "recent_detail_reset_url": (
            detail_next_url
        ),
        "recent_summary_items": [
            {"key": "approach_total", "label": "合計AP", "value": f"{int(recent_totals.get('approach_count') or 0):,}"},
            {"key": "communication_total", "label": "合計CM", "value": f"{int(recent_totals.get('communication_count') or 0):,}"},
            {
                "key": "count_total",
                "label": "合計件数",
                "value": _final_count_text(department_code=department.code, totals=recent_totals),
                "subtext": _final_count_subtext(department_code=department.code, totals=recent_totals),
            },
            {"key": "amount_total", "label": "合計金額", "value": _final_amount_text(totals=recent_totals)},
            {
                "key": "adjustment_count_total",
                "label": "補正実績件数",
                "value": _final_count_text(department_code=department.code, totals=recent_adjustment_totals),
                "subtext": _final_count_subtext(department_code=department.code, totals=recent_adjustment_totals),
            },
            {
                "key": "adjustment_amount_total",
                "label": "補正実績金額",
                "value": _final_amount_text(totals=recent_adjustment_totals),
            },
            {"key": "active_days", "label": "稼働日数", "value": f"{recent_active_days:,}日"},
        ],
        "activity_trend": activity_trend,
        "trend_date_links": build_trend_date_links(activity_trend),
        "detail_history_url": (
            reverse("performance_member_history_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history")
        ),
        "recent_detail_ajax_url": (
            reverse("performance_member_detail_recent_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_dashboard_recent_detail")
        ),
        "department_month_progress": department_month_progress,
        "department_period_progress": department_period_progress,
        "member_month_progress": build_progress_card(
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
        "member_period_progress": build_progress_card(
            label="個人の路程目標",
            actual_amount=member_period_actual_amount,
            target_amount=int(member_period_target.target_amount if member_period_target else 0),
            summary_text=f"{member.name} さんの{_period_display_label(current_period)}進捗",
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
        "can_edit": True,
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

    detail_payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
        limit=5,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=_field_count_text,
            field_amount_text=_field_amount_text,
            **kwargs,
        ),
    )
    entry_rows = detail_payload["entry_rows"]
    entry_edit_next_url = request.get_full_path()
    can_edit = _can_edit_member_performance(is_admin=is_admin, readonly_member_view=False)
    if can_edit:
        attach_transaction_edit_urls(entry_rows=entry_rows, next_url=entry_edit_next_url)
        for row in entry_rows:
            row["edit_url"] = (
                f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
                f"?{urlencode({'next': entry_edit_next_url})}"
            )
            row["delete_url"] = (
                f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
                f"?{urlencode({'next': entry_edit_next_url})}"
            )
    adjustment_rows = detail_payload["adjustment_rows"]
    activity_trend = build_member_activity_trend(
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
    department_adjustment_amount = sum_adjustment_amount(
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
    )
    member_adjustment_amount = sum_adjustment_amount(
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
            resolve_month_target_amounts_by_code(
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
        department_card = build_progress_card(
            label="全体の月目標",
            actual_amount=department_actual_amount,
            target_amount=department_target_amount,
            summary_text=f"{department.code} 全体の{scope.month_start:%Y/%m}進捗",
            base_actual_amount=max(department_actual_amount - department_adjustment_amount, 0),
            adjustment_amount=department_adjustment_amount,
        )
        department_card["contribution"] = build_contribution_summary(
            member_actual_amount=member_actual_amount,
            department_actual_amount=department_actual_amount,
        )
        department_progress_cards.append(department_card)
        member_progress_cards.append(
            build_progress_card(
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
            resolve_period_target_amounts_by_code(
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
        department_card = build_progress_card(
            label="全体の路程目標",
            actual_amount=department_actual_amount,
            target_amount=department_target_amount,
            summary_text=f"{department.code} 全体の{scope.period.name}進捗",
            base_actual_amount=max(department_actual_amount - department_adjustment_amount, 0),
            adjustment_amount=department_adjustment_amount,
        )
        department_card["contribution"] = build_contribution_summary(
            member_actual_amount=member_actual_amount,
            department_actual_amount=department_actual_amount,
        )
        department_progress_cards.append(department_card)
        member_progress_cards.append(
            build_progress_card(
                label="個人の路程目標",
                actual_amount=member_actual_amount,
                target_amount=int(member_target.target_amount if member_target else 0),
                summary_text=f"{member.name} さんの{scope.period.name}進捗",
                base_actual_amount=max(member_actual_amount - member_adjustment_amount, 0),
                adjustment_amount=member_adjustment_amount,
            )
        )

    return {
        "nav_items": _performance_member_page_nav_links(
            member=member,
            department=department,
            is_admin=is_admin,
        ),
        "member": member,
        "department": department,
        "is_admin_view": is_admin,
        "readonly_member_view": False,
        "can_edit": can_edit,
        "dashboard_scope": dashboard_scope,
        "dashboard_month": dashboard_month,
        "dashboard_period": dashboard_period,
        "dashboard_periods": period_options_active_first(target_date=today),
        "dashboard_start": dashboard_start,
        "dashboard_end": dashboard_end,
        "history_scope": scope,
        "activity_trend": activity_trend,
        "trend_date_links": build_trend_date_links(activity_trend),
        "department_progress_cards": department_progress_cards,
        "member_progress_cards": member_progress_cards,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "detail_limit": 5,
        "detail_limit_step": 5,
        "detail_has_more": detail_payload["has_more"],
        "detail_filter_mode": "input" if scope.scope == "range" else "buttons",
        "detail_filter_dates": detail_payload["filter_dates"],
        "detail_selected_date": None,
        "detail_ajax_url": (
            reverse("performance_member_history_detail_list", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history_list")
        ),
        "detail_reset_url": (
            reverse("performance_member_history_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history")
        ),
    }


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
    dashboard_snapshot = _build_performance_dashboard_snapshot(
        department=dashboard_department,
        target_month=dashboard_month,
        period=dashboard_period,
    )
    nav_items = _performance_nav_items()
    if resolve_request_role(request) == ROLE_REPORT:
        nav_items = _performance_member_nav_items(is_admin=False)
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
        **_build_department_today_detail_context(
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
        "nav_items": _performance_nav_items(),
        "filter_form": filter_form,
        "page_obj": page_obj,
        "paginator": paginator,
        "summary_rows": summary_rows,
        "current_query_string": current_query.urlencode(),
    }
    return render(request, "performance/admin_entries.html", context)


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
    nav_items = _performance_nav_items()
    if resolve_request_role(request) == ROLE_REPORT:
        nav_items = _performance_member_nav_items(is_admin=False)
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
        **_build_department_today_detail_context(
            department=dashboard_department,
            target_date=today,
            next_url=request.get_full_path(),
        ),
    }
    return render(request, "performance/history.html", context)


@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_send_activity_reminder(request: HttpRequest, entry_id: int) -> HttpResponse:
    if request.method != "POST":
        raise Http404
    entry = get_object_or_404(
        MemberDailyMetricEntry.objects.select_related("member", "department"),
        pk=entry_id,
        activity_closed=False,
    )
    sender_member = getattr(request.user, "member_profile", None)
    target_member = entry.member
    history = send_member_direct_mail(
        target_member=target_member,
        sender_member=sender_member,
        department=entry.department,
        sender_name_override="おつかれさまです",
        subject=f"【リマインド】{entry.entry_date:%Y/%m/%d} の活動入力をお願いします",
        body=(
            f"{target_member.name}さん\n\n"
            "活動お疲れ様でした。活動終了が確認できていませんので"
            "お手数ですが入力をよろしくお願いします。"
        ),
    )
    status = (
        f"{target_member.name}さんへリマインドを送信しました。"
        if history.status == MailSendHistory.STATUS_SENT
        else f"{target_member.name}さんへのリマインド送信に失敗しました。"
    )
    next_url = request.POST.get("next") or reverse("performance_index")
    separator = "&" if "?" in next_url else "?"
    return redirect(f"{_performance_next_url(next_url, fallback=reverse('performance_index'))}{separator}{urlencode({'status': status})}")


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
        "nav_items": _performance_nav_items() if is_admin else _performance_member_nav_items(is_admin=False),
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
    back_url = _performance_next_url(next_url, fallback=fallback_url)
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
    back_url = _performance_next_url(next_url, fallback=fallback_url)
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
        "nav_items": _performance_nav_items() if is_admin else _performance_member_nav_items(is_admin=False),
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
    back_url = _performance_next_url(next_url, fallback=fallback_url)
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
    context = _build_member_dashboard_context(request=request, member=member, department=department, is_admin=True)
    return render(request, "performance/member_detail.html", context)


@require_performance_roles(ROLE_ADMIN)
def performance_member_history_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = _resolve_performance_member_department_or_404(member=member, department_id=department_id)
    context = _build_member_history_context(request=request, member=member, department=department, is_admin=True)
    return render(request, "performance/member_history.html", context)


def _render_member_history_day_detail_response(
    *,
    request: HttpRequest,
    member,
    department,
    is_admin=False,
    readonly_member_view=False,
):
    can_edit = _can_edit_member_performance(is_admin=is_admin, readonly_member_view=readonly_member_view)
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
    entry_edit_next_url = (
        reverse("performance_member_history_insight", args=[member.id, department.id])
        if readonly_member_view
        else reverse("performance_member_history_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_history")
    )
    if can_edit:
        for row in entry_rows:
            row["edit_url"] = f"{reverse('performance_entry_edit', args=[row['entry'].id])}?{urlencode({'next': entry_edit_next_url})}"
            row["delete_url"] = f"{reverse('performance_entry_delete', args=[row['entry'].id])}?{urlencode({'next': entry_edit_next_url})}"
        attach_transaction_edit_urls(entry_rows=entry_rows, next_url=entry_edit_next_url)
    adjustment_rows = list(
        MetricAdjustment.objects.filter(
            member=member,
            department=department,
            target_date=selected_date,
        ).order_by("-target_date", "-created_at")
    )
    context = {
        "member": member,
        "department": department,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "detail_heading": f"{selected_date:%Y/%m/%d} の日次実績",
        "detail_adjustment_heading": f"{selected_date:%Y/%m/%d} の補正実績",
        "detail_description": "グラフで選択した1日分の実績です。",
        "show_reset_detail": True,
        "detail_reset_url": entry_edit_next_url,
        "readonly_member_view": readonly_member_view,
        "can_edit": can_edit,
    }
    return render(request, "performance/partials/member_history_day_detail_cards.html", context)


def _render_member_history_list_response(
    *,
    request: HttpRequest,
    member,
    department,
    is_admin=False,
    readonly_member_view=False,
):
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
    selected_date = _parse_selected_date(request.GET.get("date"))
    try:
        requested_limit = int(request.GET.get("limit") or 5)
    except (TypeError, ValueError):
        requested_limit = 5
    limit = max(5, min(requested_limit, 30))
    payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=scope.start_date,
        end_date=scope.end_date,
        selected_date=selected_date,
        limit=limit,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=_field_count_text,
            field_amount_text=_field_amount_text,
            **kwargs,
        ),
    )
    entry_edit_next_url = request.get_full_path()
    entry_rows = payload["entry_rows"]
    can_edit = _can_edit_member_performance(is_admin=is_admin, readonly_member_view=readonly_member_view)
    if can_edit:
        for row in entry_rows:
            row["edit_url"] = (
                f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
                f"?{urlencode({'next': entry_edit_next_url})}"
            )
            row["delete_url"] = (
                f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
                f"?{urlencode({'next': entry_edit_next_url})}"
            )
        attach_transaction_edit_urls(entry_rows=entry_rows, next_url=entry_edit_next_url)
    context = {
        "member": member,
        "department": department,
        "entry_rows": entry_rows,
        "adjustment_rows": payload["adjustment_rows"],
        "detail_heading": f"{scope.label} の日次実績",
        "detail_adjustment_heading": f"{scope.label} の補正実績",
        "detail_description": (
            f"{selected_date:%Y/%m/%d} の実績を表示中"
            if selected_date
            else "対象期間の日次実績と補正実績です。"
        ),
        "show_reset_detail": False,
        "readonly_member_view": readonly_member_view,
        "can_edit": can_edit,
        "detail_limit": limit,
        "detail_limit_step": 5,
        "detail_has_more": payload["has_more"],
        "detail_filter_mode": "input" if scope.scope == "range" else "buttons",
        "detail_filter_dates": payload["filter_dates"],
        "detail_selected_date": selected_date,
        "detail_ajax_url": (
            reverse("performance_member_history_insight_list", args=[member.id, department.id])
            if readonly_member_view
            else reverse("performance_member_history_detail_list", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history_list")
        ),
        "detail_reset_url": (
            reverse("performance_member_history_insight", args=[member.id, department.id])
            if readonly_member_view
            else reverse("performance_member_history_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_history")
        ),
    }
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
    context = _build_member_dashboard_detail_context(
        member=member,
        department=department,
        entry_rows=entry_rows,
        adjustment_rows=adjustment_rows,
        is_admin=is_admin,
        readonly_member_view=readonly_member_view,
        selected_date=selected_date,
        reset_url=reset_url,
    )
    can_edit = _can_edit_member_performance(is_admin=is_admin, readonly_member_view=readonly_member_view)
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
    today = timezone.localdate()
    recent_start = today - timedelta(days=29)
    recent_end = today
    selected_date = _parse_selected_date(request.GET.get("date"))
    try:
        requested_limit = int(request.GET.get("limit") or 5)
    except (TypeError, ValueError):
        requested_limit = 5
    limit = max(5, min(requested_limit, 30))
    payload = build_entry_adjustment_detail_payload(
        member=member,
        department=department,
        start_date=recent_start,
        end_date=recent_end,
        selected_date=selected_date,
        limit=limit,
        entry_rows_builder=lambda **kwargs: build_member_dashboard_entry_rows(
            field_count_text=_field_count_text,
            field_amount_text=_field_amount_text,
            **kwargs,
        ),
    )
    detail_history_url = (
        reverse("performance_member_history_insight", args=[member.id, department.id])
        if readonly_member_view
        else reverse("performance_member_history_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_history")
    )
    recent_detail_ajax_url = (
        reverse("performance_member_insight_recent_detail", args=[member.id, department.id])
        if readonly_member_view
        else reverse("performance_member_detail_recent_detail", args=[member.id, department.id])
        if is_admin
        else reverse("performance_member_dashboard_recent_detail")
    )
    context = {
        "member": member,
        "department": department,
        "recent_entry_rows": payload["entry_rows"],
        "recent_adjustment_rows": payload["adjustment_rows"],
        "detail_heading": "直近30日の実績",
        "detail_adjustment_heading": "直近30日の補正実績",
        "detail_description": (
            f"{selected_date:%Y/%m/%d} の実績を表示中"
            if selected_date
            else f"{recent_start:%Y/%m/%d} - {recent_end:%Y/%m/%d}"
        ),
        "show_reset_detail": False,
        "detail_history_url": detail_history_url,
        "readonly_member_view": readonly_member_view,
        "recent_detail_start": recent_start,
        "recent_detail_end": recent_end,
        "recent_detail_limit": limit,
        "recent_detail_limit_step": 5,
        "recent_detail_selected_date": selected_date,
        "recent_detail_has_more": payload["has_more"],
        "recent_detail_ajax_url": recent_detail_ajax_url,
        "recent_detail_reset_url": (
            reverse("performance_member_insight", args=[member.id, department.id])
            if readonly_member_view
            else reverse("performance_member_detail", args=[member.id, department.id])
            if is_admin
            else reverse("performance_member_dashboard")
        ),
        "can_edit": _can_edit_member_performance(is_admin=is_admin, readonly_member_view=readonly_member_view),
    }
    if context["can_edit"]:
        attach_transaction_edit_urls(
            entry_rows=context["recent_entry_rows"],
            next_url=context["recent_detail_reset_url"],
        )
        for row in context["recent_entry_rows"]:
            row["edit_url"] = (
                f"{reverse('performance_entry_edit', args=[row['entry'].id])}"
                f"?{urlencode({'next': context['recent_detail_reset_url']})}"
            )
            row["delete_url"] = (
                f"{reverse('performance_entry_delete', args=[row['entry'].id])}"
                f"?{urlencode({'next': context['recent_detail_reset_url']})}"
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
    context = _build_member_dashboard_context(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
    )
    context["readonly_member_view"] = True
    context["can_edit"] = _can_edit_member_performance(
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )
    context["nav_items"] = _performance_member_page_nav_links(
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
    context = _build_member_history_context(
        request=request,
        member=member,
        department=department,
        is_admin=request.user.is_staff or request.user.is_superuser,
    )
    context["readonly_member_view"] = True
    context["can_edit"] = _can_edit_member_performance(
        is_admin=request.user.is_staff or request.user.is_superuser,
        readonly_member_view=True,
    )
    context["nav_items"] = _performance_member_page_nav_links(
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
def performance_member_dashboard_day_detail(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        raise Http404
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = _resolve_member_card_department(member=member)
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
    department = _resolve_member_card_department(member=member)
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
    department = _resolve_member_card_department(member=member)
    if department is None:
        raise Http404
    context = _build_member_history_context(request=request, member=member, department=department, is_admin=False)
    return render(request, "performance/member_history.html", context)


@require_performance_roles(ROLE_ADMIN, ROLE_REPORT)
def performance_member_history_list(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff or request.user.is_superuser:
        raise Http404
    member = getattr(request.user, "member_profile", None)
    if member is None:
        raise Http404
    department = _resolve_member_card_department(member=member)
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
    department = _resolve_member_card_department(member=member)
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
        "nav_items": _performance_nav_items(),
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
        return redirect(f"{_performance_next_url(next_url, fallback=reverse('performance_admin_entries'))}{separator}deleted=summary")
    separator = "&" if "?" in next_url else "?"
    return redirect(f"{_performance_next_url(next_url, fallback=reverse('performance_admin_entries'))}{separator}status=summary_not_empty")


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
        adjustments_queryset = _combined_adjustment_list_rows(list_filter_form.cleaned_data)
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
        "nav_items": _performance_nav_items(),
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
