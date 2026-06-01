from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse

from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry


def build_admin_entry_management_page(*, cleaned_data, page_number, next_url):
    queryset = _filtered_summary_queryset(cleaned_data)
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(page_number or 1)
    return {
        "paginator": paginator,
        "page_obj": page_obj,
        "summary_rows": build_admin_entry_summary_rows(
            summaries=page_obj.object_list,
            next_url=next_url,
        ),
    }


def _filtered_summary_queryset(cleaned_data):
    queryset = DepartmentDailyMetricSummary.objects.select_related("department").order_by(
        "-entry_date",
        "department__code",
        "-id",
    )
    department = cleaned_data.get("department")
    member = cleaned_data.get("member")
    date_from = cleaned_data.get("date_from")
    date_to = cleaned_data.get("date_to")
    if department is not None:
        queryset = queryset.filter(department=department)
    if date_from is not None:
        queryset = queryset.filter(entry_date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(entry_date__lte=date_to)
    if member is None:
        return queryset
    member_entries = MemberDailyMetricEntry.objects.filter(member=member)
    if department is not None:
        member_entries = member_entries.filter(department=department)
    if date_from is not None:
        member_entries = member_entries.filter(entry_date__gte=date_from)
    if date_to is not None:
        member_entries = member_entries.filter(entry_date__lte=date_to)
    pair_filters = Q()
    has_pairs = False
    for department_id, entry_date in member_entries.values_list("department_id", "entry_date").distinct():
        has_pairs = True
        pair_filters |= Q(department_id=department_id, entry_date=entry_date)
    if not has_pairs:
        return queryset.none()
    return queryset.filter(pair_filters)


def build_admin_entry_summary_rows(*, summaries, next_url):
    summaries = list(summaries)
    if not summaries:
        return []
    pair_filters = Q()
    entry_map = {}
    for summary in summaries:
        pair = (summary.department_id, summary.entry_date)
        pair_filters |= Q(department_id=summary.department_id, entry_date=summary.entry_date)
        entry_map[pair] = []
    entries = (
        MemberDailyMetricEntry.objects.filter(pair_filters)
        .select_related("member", "department")
        .order_by("member__name", "id")
    )
    for entry in entries:
        pair = (entry.department_id, entry.entry_date)
        entry_map[pair].append(
            {
                "entry": entry,
                "member_name": entry.member.name,
                "location_name": entry.location_name or "-",
                "approach_count": int(entry.approach_count or 0),
                "communication_count": int(entry.communication_count or 0),
                "count_text": f"{int(entry.result_count or 0)}件",
                "amount_text": f"{int(entry.support_amount or 0):,}円",
                "edit_url": f"{reverse('performance_entry_edit', args=[entry.id])}?next={next_url}",
                "delete_url": f"{reverse('performance_entry_delete', args=[entry.id])}?next={next_url}",
            }
        )
    rows = []
    for summary in summaries:
        rows.append(
            {
                "summary": summary,
                "department_code": summary.department.code,
                "entry_date": summary.entry_date,
                "approach_count": int(summary.approach_count or 0),
                "communication_count": int(summary.communication_count or 0),
                "count_text": f"{int(summary.result_count or 0)}件",
                "amount_text": f"{int(summary.support_amount or 0):,}円",
                "entries": entry_map.get((summary.department_id, summary.entry_date), []),
            }
        )
    return rows
