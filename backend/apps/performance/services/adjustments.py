from django.db.models import Q
from django.urls import reverse

from apps.dairymetrics.models import MetricAdjustment, WVMetricCancellation


def _adjustment_source_types_matching_query(query):
    normalized_query = (query or "").strip().casefold()
    if not normalized_query:
        return []
    return [
        source_type
        for source_type, label in MetricAdjustment.SOURCE_CHOICES
        if normalized_query in label.casefold()
    ]


def _adjustment_search_filter(query):
    filters = (
        Q(member__name__icontains=query)
        | Q(location_name__icontains=query)
        | Q(source_type__icontains=query)
        | Q(department__code__icontains=query)
    )
    source_types = _adjustment_source_types_matching_query(query)
    if source_types:
        filters |= Q(source_type__in=source_types)
    return filters


def filtered_adjustments_queryset(cleaned_data):
    queryset = MetricAdjustment.objects.select_related(
        "member",
        "department",
        "created_by",
    ).order_by("-target_date", "-created_at")
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
        queryset = queryset.filter(_adjustment_search_filter(query))
    return queryset


def _filtered_adjustments_list_queryset(cleaned_data):
    queryset = MetricAdjustment.objects.select_related(
        "member",
        "department",
        "created_by",
    ).order_by("-target_date", "-created_at")
    department = cleaned_data.get("department")
    query = (cleaned_data.get("q") or "").strip()
    if department:
        queryset = queryset.filter(department=department)
    if query:
        queryset = queryset.filter(_adjustment_search_filter(query))
    return queryset


def _filtered_cancellations_list_queryset(cleaned_data):
    queryset = WVMetricCancellation.objects.select_related(
        "member",
        "department",
        "created_by",
    ).order_by("-target_date", "-created_at")
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
            queryset = WVMetricCancellation.objects.select_related(
                "member",
                "department",
                "created_by",
            ).order_by("-target_date", "-created_at")
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


def combined_adjustment_list_rows(cleaned_data):
    rows = [
        _adjustment_list_row(adjustment)
        for adjustment in _filtered_adjustments_list_queryset(cleaned_data)
    ]
    rows.extend(
        _cancellation_list_row(cancellation)
        for cancellation in _filtered_cancellations_list_queryset(cleaned_data)
    )
    return sorted(
        rows,
        key=lambda row: (row["target_date"], row["created_at"]),
        reverse=True,
    )
