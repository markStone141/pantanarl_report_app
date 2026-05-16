from datetime import date

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, require_roles
from apps.accounts.models import Department, Member, MemberDepartment
from apps.dairymetrics.forms import MemberScopeTargetForm
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


def _performance_nav_items():
    return [
        ("dashboard_index", "管理者ページ"),
        ("member_settings", "メンバー管理"),
        ("department_settings", "部署管理"),
        ("performance_index", "実績管理"),
        ("performance_adjustments", "補正実績"),
        ("mail_integration_settings", "メール連携"),
        ("mail_group_settings", "メールグループ"),
    ]


def _performance_member_nav_items(*, is_admin=False):
    if is_admin:
        return [
            ("performance_index", "実績管理"),
            ("performance_adjustments", "補正実績"),
        ]
    return [
        ("performance_member_dashboard", "実績ダッシュボード"),
    ]


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
    total_count = (
        int(entry.result_count or 0)
        + int(adjustment_totals["result_count"])
        + int(adjustment_totals["return_postal_count"])
        + int(adjustment_totals["return_qr_count"])
    )
    return f"{total_count}件"


def _amount_text(entry, adjustment_totals):
    total_amount = (
        int(entry.support_amount or 0)
        + int(adjustment_totals["support_amount"])
        + int(adjustment_totals["return_postal_amount"])
        + int(adjustment_totals["return_qr_amount"])
    )
    return f"{total_amount:,}円"


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


def _progress_rate(actual, target):
    if target <= 0:
        return None
    return round((actual / target) * 100, 1)


def _build_progress_card(*, label, actual_amount, target_amount, summary_text):
    rate = _progress_rate(actual_amount, target_amount)
    return {
        "label": label,
        "actual_amount": actual_amount,
        "actual_amount_text": f"{actual_amount:,}円",
        "target_amount": target_amount,
        "target_amount_text": f"{target_amount:,}円",
        "rate": rate,
        "rate_text": "-" if rate is None else f"{rate}%",
        "summary_text": summary_text,
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


def _build_active_member_cards(*, members, today, current_period, selected_department=None):
    cards = []
    month_start = today.replace(day=1)
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
            month_start,
            today,
            include_adjustments=True,
        )
        period_totals = collect_member_final_actual_totals(
            member,
            department,
            current_period.start_date if current_period else today,
            min(current_period.end_date, today) if current_period else today,
            include_adjustments=True,
        )
        month_target = MemberMonthMetricTarget.objects.filter(
            member=member,
            department=department,
            target_month=month_start,
        ).first()
        period_target = (
            MemberPeriodMetricTarget.objects.filter(
                member=member,
                department=department,
                period=current_period,
            ).first()
            if current_period
            else None
        )
        month_actual_amount = (
            int(month_totals.get("support_amount") or 0)
            + int(month_totals.get("return_postal_amount") or 0)
            + int(month_totals.get("return_qr_amount") or 0)
        )
        period_actual_amount = (
            int(period_totals.get("support_amount") or 0)
            + int(period_totals.get("return_postal_amount") or 0)
            + int(period_totals.get("return_qr_amount") or 0)
        )
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
                "month_target_progress": _build_member_target_progress(
                    label="月目標達成率",
                    actual_amount=month_actual_amount,
                    target_amount=int(month_target.target_amount if month_target else 0),
                ),
                "period_amount_text": _final_amount_text(totals=period_totals),
                "period_count_text": _final_count_text(department_code=department.code, totals=period_totals),
                "period_target_progress": _build_member_target_progress(
                    label="路程目標達成率",
                    actual_amount=period_actual_amount,
                    target_amount=int(period_target.target_amount if period_target else 0),
                ),
                "recent_date_text": recent_date_text,
                "recent_amount_text": recent_amount_text,
                "recent_count_text": recent_count_text,
                "recent_sort_date": recent_sort_date,
                "detail_url": reverse(
                    "performance_member_detail",
                    args=[member.id, department.id],
                ),
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


def _build_performance_dashboard_snapshot(*, department=None):
    today = timezone.localdate()
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

    target_month = today.replace(day=1)
    period = _resolve_current_period(today)
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
            )
        )

    return {
        "today": today,
        "activity_in_progress": _build_activity_member_rows(activity_in_progress),
        "activity_finished": _build_activity_member_rows(activity_finished),
        "active_member_cards": _build_active_member_cards(
            members=active_members,
            today=today,
            current_period=period,
            selected_department=department,
        ),
        "month_progress_cards": month_progress_cards,
        "period_progress_cards": period_progress_cards,
        "current_period": period,
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


def _build_member_activity_trend(*, member, department):
    latest_entries = list(
        MemberDailyMetricEntry.objects.select_related("department")
        .filter(member=member, department=department)
        .order_by("-entry_date", "-id")[:120]
    )
    if not latest_entries:
        return {
            "labels": [],
            "amounts": [],
            "counts": [],
            "has_data": False,
            "count_label": "件数",
            "default_visible_count": 0,
        }
    latest_entries.reverse()
    adjustment_totals_map = _build_adjustment_totals_map(latest_entries)
    labels = []
    amounts = []
    counts = []
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
        amounts.append(
            int(entry.support_amount or 0)
            + int(adjustment_totals["support_amount"])
            + int(adjustment_totals["return_postal_amount"])
            + int(adjustment_totals["return_qr_amount"])
        )
        if department.code == "WV":
            counts.append(
                int(entry.cs_count or 0)
                + int(entry.refugee_count or 0)
                + int(adjustment_totals["cs_count"])
                + int(adjustment_totals["refugee_count"])
            )
        else:
            counts.append(
                int(entry.result_count or 0)
                + int(adjustment_totals["result_count"])
                + int(adjustment_totals["return_postal_count"])
                + int(adjustment_totals["return_qr_count"])
            )
    return {
        "labels": labels,
        "amounts": amounts,
        "counts": counts,
        "has_data": True,
        "count_label": "件数" if department.code != "WV" else "件数相当",
        "default_visible_count": min(30, len(labels)),
    }


def _build_member_dashboard_context(*, request, member, department, is_admin=False):
    today = timezone.localdate()
    selected_month = _parse_selected_month(request.GET.get("month"), default=today)
    selected_month_end = min(_month_end(selected_month), today)
    current_period = _resolve_current_period(today)
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
    activity_trend = _build_member_activity_trend(member=member, department=department)

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

    return {
        "nav_items": _performance_member_nav_items(is_admin=is_admin),
        "member": member,
        "department": department,
        "month_label": selected_month.strftime("%Y/%m"),
        "period_label": current_period.name if current_period else "路程未設定",
        "selected_month": selected_month,
        "entry_rows": entry_rows,
        "adjustment_rows": adjustment_rows,
        "activity_trend": activity_trend,
        "department_month_progress": _build_progress_card(
            label="全体の月目標",
            actual_amount=int(department_month_totals.get("support_amount") or 0)
            + int(department_month_totals.get("return_postal_amount") or 0)
            + int(department_month_totals.get("return_qr_amount") or 0),
            target_amount=department_month_target_amount,
            summary_text=f"{department.code} 全体の{selected_month:%Y/%m}進捗",
        ),
        "department_period_progress": _build_progress_card(
            label="全体の路程目標",
            actual_amount=int(department_period_totals.get("support_amount") or 0)
            + int(department_period_totals.get("return_postal_amount") or 0)
            + int(department_period_totals.get("return_qr_amount") or 0),
            target_amount=department_period_target_amount,
            summary_text=f"{department.code} 全体の現在路程進捗",
        ),
        "member_month_progress": _build_progress_card(
            label="個人の月目標",
            actual_amount=int(member_month_totals.get("support_amount") or 0)
            + int(member_month_totals.get("return_postal_amount") or 0)
            + int(member_month_totals.get("return_qr_amount") or 0),
            target_amount=int(member_month_target.target_amount if member_month_target else 0),
            summary_text=f"{member.name} さんの{selected_month:%Y/%m}進捗",
        ),
        "member_period_progress": _build_progress_card(
            label="個人の路程目標",
            actual_amount=int(member_period_totals.get("support_amount") or 0)
            + int(member_period_totals.get("return_postal_amount") or 0)
            + int(member_period_totals.get("return_qr_amount") or 0),
            target_amount=int(member_period_target.target_amount if member_period_target else 0),
            summary_text=f"{member.name} さんの現在路程進捗",
        ),
        "month_target_form": MemberScopeTargetForm(
            member=member,
            scope="month",
            department=department,
            target_month=selected_month,
        ),
        "period_target_form": MemberScopeTargetForm(
            member=member,
            scope="period",
            department=department,
            period=current_period,
        ) if current_period else None,
        "is_admin_view": is_admin,
    }


@require_roles(ROLE_ADMIN)
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
    dashboard_department = filter_form.cleaned_data.get("department") if filter_form.is_valid() else None
    dashboard_snapshot = _build_performance_dashboard_snapshot(department=dashboard_department)
    context = {
        "nav_items": _performance_nav_items(),
        "filter_form": filter_form,
        "page_obj": page_obj,
        "paginator": paginator,
        "entry_rows": entry_rows,
        "adjustments_preview": adjustments_preview,
        "current_query_string": current_query.urlencode(),
        "dashboard_snapshot": dashboard_snapshot,
    }
    return render(request, "performance/index.html", context)


@require_roles(ROLE_ADMIN)
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


@require_roles(ROLE_ADMIN)
def performance_member_detail(request: HttpRequest, member_id: int, department_id: int) -> HttpResponse:
    member = get_object_or_404(Member.objects.select_related("default_department"), pk=member_id)
    department = get_object_or_404(Department, pk=department_id, is_active=True)
    if not MemberDepartment.objects.filter(member=member, department=department).exists() and member.default_department_id != department.id:
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


@require_roles(ROLE_ADMIN, ROLE_REPORT)
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


@require_roles(ROLE_ADMIN)
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
    context = {
        "nav_items": _performance_nav_items(),
        "filter_form": filter_form,
        "form": form,
        "edit_adjustment": edit_adjustment,
        "status_message": status_message,
        "page_obj": page_obj,
        "paginator": paginator,
        "adjustments": page_obj.object_list,
    }
    return render(request, "performance/adjustments.html", context)


@require_roles(ROLE_ADMIN)
def performance_adjustment_delete(request: HttpRequest, adjustment_id: int) -> HttpResponse:
    adjustment = get_object_or_404(MetricAdjustment, pk=adjustment_id)
    if request.method == "POST":
        adjustment.delete()
    return redirect(reverse("performance_adjustments"))
