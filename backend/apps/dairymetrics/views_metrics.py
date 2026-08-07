from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.common.target_periods import period_options_active_first

from .auth import get_member_profile, require_dairymetrics_member
from .services.entry_context import parse_month_input, resolve_metrics_v2_department
from .services.metrics_v2 import build_metrics_v2_dashboard_payload, resolve_metrics_v2_scope
from .services.report_exports import build_report_ai_text, build_report_export_payload
from .services.reports import build_metrics_scope_report
from .view_helpers import login_redirect_url, member_directory_queryset, requested_or_current_period


@require_dairymetrics_member
def metrics_v2(request: HttpRequest) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    departments, selected_department = resolve_metrics_v2_department(request=request, member=viewer_member)
    if not selected_department:
        return redirect(login_redirect_url(request.user))
    selected_member = None
    raw_member_id = (request.GET.get("member") or "").strip()
    if request.user.is_staff and raw_member_id.isdigit():
        selected_member = (
            member_directory_queryset()
            .filter(pk=int(raw_member_id), department_links__department=selected_department)
            .distinct()
            .first()
        )

    today = timezone.localdate()
    requested_scope = (request.GET.get("scope") or "recent").strip()
    requested_month = parse_month_input(request.GET.get("month") or "")
    available_periods = period_options_active_first(target_date=today, limit=18)
    requested_period = None
    if requested_scope == "period":
        requested_period = requested_or_current_period(request, today=today)
    requested_start_date = parse_date((request.GET.get("start_date") or "").strip())
    requested_end_date = parse_date((request.GET.get("end_date") or "").strip())

    scope = resolve_metrics_v2_scope(
        today=today,
        scope=requested_scope,
        requested_month=requested_month,
        requested_period=requested_period,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
    )
    payload = build_metrics_v2_dashboard_payload(
        department=selected_department,
        scope=scope,
        member=selected_member if request.user.is_staff else viewer_member,
    )
    ranking_metric_map = payload.get("ranking", {}).get("metric_map", {})
    for metric_payload in ranking_metric_map.values():
        detail_urls = []
        for row in metric_payload.get("rows", []):
            detail_url = reverse(
                "performance_member_insight",
                args=[row["member_id"], selected_department.id],
            )
            row["detail_url"] = detail_url
            detail_urls.append(detail_url)
        metric_payload["detail_urls"] = detail_urls
    payload_json = {**payload, "scope": {"scope": scope.scope, "label": scope.label}}
    context = {
        "is_admin": request.user.is_staff,
        "member": viewer_member,
        "selected_member": selected_member,
        "selected_department": selected_department,
        "departments": departments,
        "scope": scope,
        "scope_value": scope.scope,
        "month_value": (scope.month_start or today.replace(day=1)).strftime("%Y-%m"),
        "start_date_value": scope.start_date.strftime("%Y-%m-%d"),
        "end_date_value": scope.end_date.strftime("%Y-%m-%d"),
        "period_options": available_periods,
        "selected_period_id": scope.period.id if scope.period else "",
        "metrics_v2_payload": payload,
        "metrics_v2_payload_json": payload_json,
    }
    return render(request, "dairymetrics/metrics_v2.html", context)


def metrics_report_data(request):
    viewer_member = get_member_profile(request.user)
    departments, selected_department = resolve_metrics_v2_department(request=request, member=viewer_member)
    if not selected_department:
        return None

    today = timezone.localdate()
    requested_scope = (request.GET.get("scope") or "month").strip()
    if requested_scope not in {"month", "period"}:
        requested_scope = "month"
    requested_month = parse_month_input(request.GET.get("month") or "")
    period_options = period_options_active_first(target_date=today)
    requested_period = None
    if requested_scope == "period":
        requested_period = requested_or_current_period(request, today=today)

    scope = resolve_metrics_v2_scope(
        today=today,
        scope=requested_scope,
        requested_month=requested_month,
        requested_period=requested_period,
    )
    if requested_scope == "period" and scope.scope != "period":
        scope = resolve_metrics_v2_scope(today=today, scope="month", requested_month=requested_month)

    report = build_metrics_scope_report(department=selected_department, scope=scope)
    export_query = urlencode(
        {
            "department": selected_department.code,
            "scope": scope.scope,
            "month": (scope.month_start or today.replace(day=1)).strftime("%Y-%m"),
            "period_id": scope.period.id if scope.period else "",
        }
    )
    return {
        "is_admin": request.user.is_staff,
        "member": viewer_member,
        "departments": departments,
        "selected_department": selected_department,
        "scope": scope,
        "scope_value": scope.scope,
        "month_value": (scope.month_start or today.replace(day=1)).strftime("%Y-%m"),
        "period_options": period_options,
        "selected_period_id": scope.period.id if scope.period else "",
        "report": report,
        "report_export_query": export_query,
    }


@require_dairymetrics_member
def metrics_report(request: HttpRequest) -> HttpResponse:
    context = metrics_report_data(request)
    if context is None:
        return redirect(login_redirect_url(request.user))
    return render(request, "dairymetrics/metrics_report.html", context)


@require_dairymetrics_member
def metrics_report_export(request: HttpRequest) -> HttpResponse:
    context = metrics_report_data(request)
    if context is None:
        return redirect(login_redirect_url(request.user))

    payload = build_report_export_payload(
        department=context["selected_department"],
        scope=context["scope"],
        report=context["report"],
    )
    export_format = (request.GET.get("format") or "txt").strip().lower()
    filename_base = (
        f"metrics-report-{context['selected_department'].code}-"
        f"{context['scope'].start_date:%Y%m%d}-{context['scope'].end_date:%Y%m%d}"
    )
    if export_format == "json":
        response = JsonResponse(
            payload,
            json_dumps_params={"ensure_ascii": False, "indent": 2},
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_base}.json"'
        return response

    response = HttpResponse(
        build_report_ai_text(payload),
        content_type="text/plain; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename_base}.txt"'
    return response
