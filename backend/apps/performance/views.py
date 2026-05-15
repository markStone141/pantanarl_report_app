from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode

from apps.accounts.auth import ROLE_ADMIN, require_roles
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MetricAdjustment

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
    context = {
        "nav_items": _performance_nav_items(),
        "filter_form": filter_form,
        "page_obj": page_obj,
        "paginator": paginator,
        "entry_rows": entry_rows,
        "adjustments_preview": adjustments_preview,
        "current_query_string": current_query.urlencode(),
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
