import logging
from urllib.parse import urlencode
from datetime import timedelta

from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, require_roles
from apps.accounts.models import Department, Member, MemberDepartment
from apps.common.dashboard_snapshot import build_member_rows, build_submission_snapshot
from apps.common.report_metrics import (
    SPLIT_COUNT_CODES,
    format_metric_triples,
    format_yen,
)
from apps.mail.models import MailRecipientGroupMember
from apps.targets.models import TargetMetric

from .services.departments import (
    department_form,
    department_form_initial,
    metric_form_for_edit,
    selected_metric_department as resolve_selected_metric_department,
    target_metric_form,
)
from .services.members import (
    build_member_bulk_queryset,
    build_member_row_payload,
    build_member_settings_queryset,
    extract_bulk_member_ids,
    member_form,
    member_form_initial,
    save_member_form,
)
from .services.target_display import (
    build_mail_metric_lines,
    build_remaining_values,
    format_adjustment_breakdown,
    build_target_metric_text,
    build_target_actual_text,
    mail_period_heading,
)
from .services.target_progress import build_target_scope_snapshot, collect_metrics_by_code

User = get_user_model()
logger = logging.getLogger(__name__)


def _format_amount_text(value):
    if isinstance(value, int):
        return f"{value:,}"
    return value


def _dashboard_index_impl(request: HttpRequest) -> HttpResponse:
    real_today = timezone.localdate()
    selected_mode = "prev" if request.GET.get("mode") == "prev" else "today"
    today = real_today - timedelta(days=1) if selected_mode == "prev" else real_today
    all_department_objects = list(Department.objects.filter(is_active=True).order_by("code"))
    submission_department_objects = [department for department in all_department_objects if department.show_in_dashboard_submission]
    progress_department_objects = [department for department in all_department_objects if department.show_in_dashboard_progress]
    target_departments = [(department.code, department.name) for department in submission_department_objects]
    snapshot = build_submission_snapshot(
        report_date=today,
        target_departments=target_departments,
    )
    target_codes = snapshot["target_codes"]
    submission_rows = snapshot["submission_rows"]
    daily_totals = snapshot["daily_totals"]
    member_totals = snapshot["member_totals"]
    for row in submission_rows:
        row["amount_text"] = _format_amount_text(row.get("amount"))

    progress_target_codes = [department.code for department in progress_department_objects]
    metrics_by_code = collect_metrics_by_code(target_codes=progress_target_codes)
    target_scope = build_target_scope_snapshot(
        target_date=today,
        target_codes=progress_target_codes,
        metrics_by_code=metrics_by_code,
    )
    current_month = target_scope["month_start"]
    month_status = target_scope["month_status"]
    month_target_values_by_code = target_scope["month_target_values_by_code"]
    month_actual_totals_by_code = target_scope["month_actual_totals_by_code"]
    month_adjustment_totals_by_code = target_scope["month_adjustment_totals_by_code"]
    current_period_label = target_scope["period_label"]
    period_status = target_scope["period_status"]
    period_target_values_by_code = target_scope["period_target_values_by_code"]
    period_actual_totals_by_code = target_scope["period_actual_totals_by_code"]
    period_adjustment_totals_by_code = target_scope["period_adjustment_totals_by_code"]
    current_period_range = target_scope["period_range"]
    metric_detail_by_code = target_scope["metric_detail_by_code"]

    target_progress_rows = []
    for department in progress_department_objects:
        code = department.code
        label = department.name
        _, _, month_rate_text = format_metric_triples(
            metrics=metrics_by_code[code],
            target_values=month_target_values_by_code.get(code, {}),
            actual_totals=month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        _, _, period_rate_text = format_metric_triples(
            metrics=metrics_by_code[code],
            target_values=period_target_values_by_code.get(code, {}),
            actual_totals=period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        target_progress_rows.append(
            {
                "label": label,
                "month_target": build_target_metric_text(
                    metrics=metrics_by_code[code],
                    target_values=month_target_values_by_code.get(code, {}),
                ),
                "month_actual": build_target_actual_text(
                    code=code,
                    metrics=metrics_by_code[code],
                    target_values=month_target_values_by_code.get(code, {}),
                    actual_totals=month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
                    adjustment_totals=month_adjustment_totals_by_code.get(code, {}),
                ),
                "month_rate": month_rate_text,
                "month_metrics": metric_detail_by_code.get(code, {}).get("month", []),
                "month_adjustment_note": format_adjustment_breakdown(
                    code=code,
                    totals=month_adjustment_totals_by_code.get(code, {}),
                ),
                "period_target": build_target_metric_text(
                    metrics=metrics_by_code[code],
                    target_values=period_target_values_by_code.get(code, {}),
                ),
                "period_actual": build_target_actual_text(
                    code=code,
                    metrics=metrics_by_code[code],
                    target_values=period_target_values_by_code.get(code, {}),
                    actual_totals=period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
                    adjustment_totals=period_adjustment_totals_by_code.get(code, {}),
                ),
                "period_rate": period_rate_text,
                "period_metrics": metric_detail_by_code.get(code, {}).get("period", []),
                "period_adjustment_note": format_adjustment_breakdown(
                    code=code,
                    totals=period_adjustment_totals_by_code.get(code, {}),
                ),
            }
        )

    kpi_cards = []
    for department in progress_department_objects:
        code = department.code
        label = department.name
        member_rows = build_member_rows(member_totals=member_totals, codes=[code])
        for member_row in member_rows:
            member_row["amount_text"] = _format_amount_text(member_row.get("amount", 0))
        kpi_cards.append(
            {
                "code": code,
                "title": label,
                "count": daily_totals[code]["count"],
                "amount": daily_totals[code]["amount"],
                "amount_text": _format_amount_text(daily_totals[code]["amount"]),
                "has_split_counts": code in SPLIT_COUNT_CODES,
                "cs_count": daily_totals[code]["cs_count"],
                "refugee_count": daily_totals[code]["refugee_count"],
                "members": member_rows,
            }
        )

    label_by_code = {department.code: department.name for department in submission_department_objects}

    def build_mail_template_payload(base_date):
        base_snapshot = build_submission_snapshot(
            report_date=base_date,
            target_departments=target_departments,
        )
        base_daily_totals = base_snapshot["daily_totals"]
        base_member_totals = base_snapshot["member_totals"]
        base_has_report_by_code = base_snapshot["has_report_by_code"]

        base_scope = build_target_scope_snapshot(
            target_date=base_date,
            target_codes=progress_target_codes,
            metrics_by_code=metrics_by_code,
        )
        base_month = base_scope["month_start"]
        base_month_target_values_by_code = base_scope["month_target_values_by_code"]
        base_month_actual_totals_by_code = base_scope["month_actual_totals_by_code"]
        base_month_adjustment_totals_by_code = base_scope["month_adjustment_totals_by_code"]
        base_period_target_values_by_code = base_scope["period_target_values_by_code"]
        base_period_actual_totals_by_code = base_scope["period_actual_totals_by_code"]
        base_period_adjustment_totals_by_code = base_scope["period_adjustment_totals_by_code"]
        base_metric_detail_by_code = base_scope["metric_detail_by_code"]
        base_period_name = mail_period_heading(base_scope["period_label"])
        base_period_range = base_scope["period_range"]

        section_order = [
            ("UN", "UN①"),
            ("WV", "UN②"),
            ("STYLE2", "Styleチーム"),
            ("STYLE1", "Styleチーム"),
        ]
        mail_sections = []
        for code, heading in section_order:
            if code not in label_by_code:
                continue
            member_lines = [
                {
                    "name": row["member_name"],
                    "count": row["count"],
                    "cs_count": row.get("cs_count", 0),
                    "refugee_count": row.get("refugee_count", 0),
                    "amount_text": format_yen(row["amount"]),
                }
                for row in build_member_rows(member_totals=base_member_totals, codes=[code], sort_by="input_order")
            ]
            month_metric_lines = build_mail_metric_lines(
                code=code,
                detail_rows=base_metric_detail_by_code.get(code, {}).get("month", []),
                actual_totals=base_month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
                adjustment_totals=base_month_adjustment_totals_by_code.get(code, {}),
            )
            period_metric_lines = build_mail_metric_lines(
                code=code,
                detail_rows=base_metric_detail_by_code.get(code, {}).get("period", []),
                actual_totals=base_period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
                adjustment_totals=base_period_adjustment_totals_by_code.get(code, {}),
            )
            month_remaining = build_remaining_values(base_metric_detail_by_code.get(code, {}).get("month", []))
            period_remaining = build_remaining_values(base_metric_detail_by_code.get(code, {}).get("period", []))
            has_daily_actual = any(
                int(base_daily_totals.get(code, {}).get(field, 0) or 0) > 0
                for field in ("count", "amount", "cs_count", "refugee_count")
            )
            mail_sections.append(
                {
                    "code": code,
                    "heading": heading,
                    "name": label_by_code[code],
                    "has_report": base_has_report_by_code.get(code, False) or has_daily_actual,
                    "daily_count": base_daily_totals.get(code, {}).get("count", 0),
                    "daily_cs_count": base_daily_totals.get(code, {}).get("cs_count", 0),
                    "daily_refugee_count": base_daily_totals.get(code, {}).get("refugee_count", 0),
                    "daily_amount_text": format_yen(base_daily_totals.get(code, {}).get("amount", 0)),
                    "member_lines": member_lines,
                    "period_lines": period_metric_lines,
                    "month_lines": month_metric_lines,
                    "period_remaining_text": period_remaining["text"],
                    "month_remaining_text": month_remaining["text"],
                    "period_remaining_split_text": period_remaining["split_text"],
                    "month_remaining_split_text": month_remaining["split_text"],
                }
            )

        un_wv_codes = [code for code in ["UN", "WV"] if code in label_by_code]
        un_wv_month_actual = sum(
            base_month_actual_totals_by_code.get(code, {"amount": 0})["amount"] for code in un_wv_codes
        )
        un_wv_month_target = 0
        for code in un_wv_codes:
            for metric in metrics_by_code.get(code, []):
                if metric.code == "amount":
                    un_wv_month_target += base_month_target_values_by_code.get(code, {}).get(metric.id, 0)
        un_wv_month_rate = (
            f"{(un_wv_month_actual / un_wv_month_target) * 100:.1f}%"
            if un_wv_month_target > 0
            else "-"
        )

        return {
            "report_date": base_date.strftime("%Y/%m/%d"),
            "sections": mail_sections,
            "period_name": base_period_name,
            "period_range": base_period_range,
            "un_wv_summary": {
                "actual_text": format_yen(un_wv_month_actual),
                "target_text": format_yen(un_wv_month_target),
                "rate": un_wv_month_rate,
            },
        }

    mail_template_payload_map = {
        "today": build_mail_template_payload(real_today),
        "prev": build_mail_template_payload(real_today - timedelta(days=1)),
    }

    context = {
        "today_str": today.strftime("%Y/%m/%d"),
        "submission_rows": submission_rows,
        "kpi_cards": kpi_cards,
        "target_month_summary": f"{current_month.year}/{current_month.month}",
        "target_month_status": month_status,
        "target_period_summary": current_period_label,
        "target_period_status": period_status,
        "target_period_range": current_period_range,
        "current_period_label": current_period_label,
        "target_progress_rows": target_progress_rows,
        "mail_template_payload_map": mail_template_payload_map,
        "selected_mode": selected_mode,
    }
    return render(request, "dashboard/admin.html", context)


@require_roles(ROLE_ADMIN)
def dashboard_index(request: HttpRequest) -> HttpResponse:
    try:
        return _dashboard_index_impl(request)
    except Exception:
        logger.exception("dashboard_index failed")
        today = timezone.localdate()
        return render(
            request,
            "dashboard/admin.html",
            {
                "today_str": today.strftime("%Y/%m/%d"),
                "submission_rows": [],
                "kpi_cards": [],
                "target_month_summary": f"{today.year}/{today.month}",
                "target_month_status": "-",
                "target_period_summary": "-",
                "target_period_status": "-",
                "target_period_range": "-",
                "current_period_label": "-",
                "target_progress_rows": [],
                "mail_template_payload_map": {
                    "today": {
                        "report_date": today.strftime("%Y/%m/%d"),
                        "sections": [],
                        "period_name": "-",
                        "period_range": "-",
                        "un_wv_summary": {"actual_text": "0円", "target_text": "0円", "rate": "-"},
                    },
                    "prev": {
                        "report_date": (today - timedelta(days=1)).strftime("%Y/%m/%d"),
                        "sections": [],
                        "period_name": "-",
                        "period_range": "-",
                        "un_wv_summary": {"actual_text": "0円", "target_text": "0円", "rate": "-"},
                    },
                },
                "selected_mode": "today",
            },
        )


def _member_settings_redirect(status_message: str) -> HttpResponse:
    return redirect(f"{reverse('member_settings')}?{urlencode({'status': status_message})}")


@require_roles(ROLE_ADMIN)
def member_delete(request: HttpRequest, member_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("member_settings")

    member = get_object_or_404(Member, id=member_id)
    linked_user = member.user
    member.is_active = not member.is_active
    member.save(update_fields=["is_active"])
    if not member.is_active:
        MailRecipientGroupMember.objects.filter(member=member).delete()
    if linked_user and not linked_user.is_superuser:
        linked_user.is_active = member.is_active
        linked_user.save(update_fields=["is_active"])
    return redirect("member_settings")


@require_roles(ROLE_ADMIN)
def member_purge(request: HttpRequest, member_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("member_settings")

    member = get_object_or_404(Member, id=member_id)
    if member.is_active:
        return redirect("member_settings")

    linked_user = member.user
    member.delete()
    if linked_user and not linked_user.is_superuser:
        linked_user.delete()
    return redirect("member_settings")


@require_roles(ROLE_ADMIN)
def department_settings(request: HttpRequest) -> HttpResponse:
    status_message = None
    edit_department = None
    selected_metric_department = None
    edit_metric = None

    edit_id = request.GET.get("edit")
    if edit_id and edit_id.isdigit():
        edit_department = Department.objects.filter(id=int(edit_id)).first()

    metric_department_id = request.GET.get("metric_department")
    selected_metric_department = resolve_selected_metric_department(
        raw_department_id=metric_department_id,
        edit_department=edit_department,
    )

    form = department_form(
        initial=department_form_initial(edit_department),
        edit_department=edit_department,
    )
    metric_form = target_metric_form(initial={"display_order": 1, "is_active": True})

    edit_metric_id = request.GET.get("edit_metric")
    edit_metric, metric_form = metric_form_for_edit(
        raw_metric_id=edit_metric_id,
        selected_department=selected_metric_department,
    )

    if request.method == "POST":
        action = request.POST.get("action") or "save_department"
        if action == "save_department":
            edit_department_id = request.POST.get("edit_department_id")
            if edit_department_id and edit_department_id.isdigit():
                edit_department = Department.objects.filter(id=int(edit_department_id)).first()
            form = department_form(data=request.POST, edit_department=edit_department)
            if form.is_valid():
                code = form.cleaned_data["code"].strip().upper()
                default_reporter = form.cleaned_data["default_reporter"]
                duplicate_query = Department.objects.filter(code=code)
                if edit_department_id and edit_department_id.isdigit():
                    duplicate_query = duplicate_query.exclude(id=int(edit_department_id))

                if duplicate_query.exists():
                    form.add_error("code", "この部署コードはすでに使用されています。")
                else:
                    if edit_department_id and edit_department_id.isdigit():
                        department = get_object_or_404(Department, id=int(edit_department_id))
                        if default_reporter and not MemberDepartment.objects.filter(
                            member=default_reporter,
                            department=department,
                        ).exists():
                            form.add_error(
                                "default_reporter",
                                "責任者は選択中の部署に所属するメンバーを選んでください。",
                            )
                        else:
                            department.name = form.cleaned_data["name"].strip()
                            department.code = code
                            department.default_reporter = default_reporter
                            department.show_in_dashboard_submission = form.cleaned_data["show_in_dashboard_submission"]
                            department.show_in_dashboard_progress = form.cleaned_data["show_in_dashboard_progress"]
                            department.save(
                                update_fields=[
                                    "name",
                                    "code",
                                    "default_reporter",
                                    "show_in_dashboard_submission",
                                    "show_in_dashboard_progress",
                                ]
                            )
                            status_message = f"{department.name}（{department.code}）を更新しました。"
                            edit_department = None
                            form = department_form()
                    else:
                        department = Department.objects.create(
                            name=form.cleaned_data["name"].strip(),
                            code=code,
                            default_reporter=None,
                            is_active=True,
                            show_in_dashboard_submission=form.cleaned_data["show_in_dashboard_submission"],
                            show_in_dashboard_progress=form.cleaned_data["show_in_dashboard_progress"],
                        )
                        status_message = f"{department.name}（{department.code}）を追加しました。"
                        edit_department = None
                        form = department_form()

        if action == "save_metric":
            metric_department_id = request.POST.get("metric_department_id")
            selected_metric_department = (
                Department.objects.filter(id=int(metric_department_id)).first()
                if metric_department_id and metric_department_id.isdigit()
                else None
            )
            edit_metric_id = request.POST.get("edit_metric_id")
            edit_metric = (
                TargetMetric.objects.filter(id=int(edit_metric_id)).first()
                if edit_metric_id and edit_metric_id.isdigit()
                else None
            )
            metric_form = target_metric_form(data=request.POST)
            if not selected_metric_department:
                metric_form.add_error(None, "部署を選択してください。")
            elif metric_form.is_valid():
                metric_code = metric_form.cleaned_data["code"].strip().lower()
                duplicate_query = TargetMetric.objects.filter(
                    department=selected_metric_department,
                    code=metric_code,
                )
                if edit_metric:
                    duplicate_query = duplicate_query.exclude(id=edit_metric.id)

                if duplicate_query.exists():
                    metric_form.add_error("code", "この指標コードはすでに使用されています。")
                else:
                    if edit_metric:
                        edit_metric.department = selected_metric_department
                        edit_metric.label = metric_form.cleaned_data["label"].strip()
                        edit_metric.code = metric_code
                        edit_metric.unit = metric_form.cleaned_data["unit"].strip()
                        edit_metric.display_order = metric_form.cleaned_data["display_order"]
                        edit_metric.is_active = metric_form.cleaned_data["is_active"]
                        edit_metric.save(
                            update_fields=[
                                "department",
                                "label",
                                "code",
                                "unit",
                                "display_order",
                                "is_active",
                                "updated_at",
                            ]
                        )
                        status_message = "目標指標を更新しました。"
                    else:
                        TargetMetric.objects.create(
                            department=selected_metric_department,
                            label=metric_form.cleaned_data["label"].strip(),
                            code=metric_code,
                            unit=metric_form.cleaned_data["unit"].strip(),
                            display_order=metric_form.cleaned_data["display_order"],
                            is_active=metric_form.cleaned_data["is_active"],
                        )
                        status_message = "目標指標を追加しました。"
                    metric_form = target_metric_form(initial={"display_order": 1, "is_active": True})
                    edit_metric = None

        if action == "toggle_metric":
            metric_id = request.POST.get("metric_id")
            if metric_id and metric_id.isdigit():
                metric = get_object_or_404(TargetMetric, id=int(metric_id))
                metric.is_active = not metric.is_active
                metric.save(update_fields=["is_active", "updated_at"])
                selected_metric_department = metric.department
                status_message = "目標指標の有効状態を更新しました。"

    departments = Department.objects.all()
    metrics = TargetMetric.objects.none()
    if selected_metric_department:
        metrics = TargetMetric.objects.filter(department=selected_metric_department).order_by("display_order", "id")

    return render(
        request,
        "dashboard/department_settings.html",
        {
            "form": form,
            "departments": departments,
            "edit_department": edit_department,
            "status_message": status_message,
            "metric_form": metric_form,
            "metrics": metrics,
            "selected_metric_department": selected_metric_department,
            "edit_metric": edit_metric,
        },
    )


@require_roles(ROLE_ADMIN)
def department_delete(request: HttpRequest, department_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("department_settings")

    department = get_object_or_404(Department, id=department_id)
    department.delete()
    return redirect("department_settings")


@require_roles(ROLE_ADMIN)
def member_settings(request: HttpRequest) -> HttpResponse:
    status_message = request.GET.get("status") or None
    query = (request.GET.get("q") or "").strip()
    sort = (request.GET.get("sort") or "name").strip()
    active_only = request.GET.get("active_only", "1") != "0"
    missing_email_only = request.GET.get("missing_email", "0") == "1"
    missing_login_only = request.GET.get("missing_login", "0") == "1"
    members_qs = build_member_settings_queryset(
        query=query,
        sort=sort,
        active_only=active_only,
        missing_email_only=missing_email_only,
        missing_login_only=missing_login_only,
    )
    paginator = Paginator(members_qs, 20)
    page_number = request.GET.get("page") or "1"
    page_obj = paginator.get_page(page_number)
    query_params = request.GET.copy()
    query_params.pop("page", None)
    base_query_string = query_params.urlencode()
    context = {
        "members": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "status_message": status_message,
        "query": query,
        "sort": sort,
        "active_only": active_only,
        "missing_email_only": missing_email_only,
        "missing_login_only": missing_login_only,
        "base_query_string": base_query_string,
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "list_html": render_to_string("dashboard/partials/member_settings_list.html", context, request=request),
                "has_next": page_obj.has_next(),
                "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
                "page_number": page_obj.number,
            }
        )
    return render(request, "dashboard/member_settings.html", context)


@require_roles(ROLE_ADMIN)
def member_create(request: HttpRequest) -> HttpResponse:
    status_message = ""
    if request.method == "POST":
        form = member_form(data=request.POST)
        member, status_message = save_member_form(form=form)
        if member and not form.errors:
            form = member_form()
    else:
        form = member_form()
    selected_department_ids = {str(dept_id) for dept_id in (form["departments"].value() or [])}
    department_choices = Department.objects.filter(is_active=True).order_by("code")
    return render(
        request,
        "dashboard/member_form.html",
        {
            "form": form,
            "edit_member": None,
            "department_choices": department_choices,
            "selected_department_ids": selected_department_ids,
            "page_title": "新規メンバー追加",
            "page_subtitle": "名前・所属部署・ログイン情報を設定します。",
            "submit_label": "メンバーを登録",
            "status_message": status_message,
        },
    )


@require_roles(ROLE_ADMIN)
def member_edit(request: HttpRequest, member_id: int) -> HttpResponse:
    member = get_object_or_404(Member, id=member_id)
    if request.method == "POST":
        form = member_form(data=request.POST)
        saved_member, status_message = save_member_form(form=form, member=member)
        if saved_member and not form.errors:
            return _member_settings_redirect(status_message)
    else:
        form = member_form(initial=member_form_initial(member))
    selected_department_ids = {str(dept_id) for dept_id in (form["departments"].value() or [])}
    department_choices = Department.objects.filter(is_active=True).order_by("code")
    return render(
        request,
        "dashboard/member_form.html",
        {
            "form": form,
            "edit_member": member,
            "department_choices": department_choices,
            "selected_department_ids": selected_department_ids,
            "page_title": "メンバー編集",
            "page_subtitle": "名前・所属部署・ログイン情報を更新します。",
            "submit_label": "メンバーを更新",
        },
    )


@require_roles(ROLE_ADMIN)
def member_auth_bulk_settings(request: HttpRequest) -> HttpResponse:
    query = (request.GET.get("q") or "").strip()
    selected_department_ids = [
        int(value)
        for value in request.GET.getlist("departments")
        if str(value).isdigit()
    ]
    members_qs = build_member_bulk_queryset(query=query, department_ids=selected_department_ids)
    paginator = Paginator(members_qs, 20)
    current_page_number = request.GET.get("page") or "1"
    page_obj = paginator.get_page(current_page_number)
    status_message = None
    row_errors = {}
    row_login_inputs = {}
    row_email_inputs = {}
    row_un_activity_code_inputs = {}

    if request.method == "POST":
        updated_count = 0
        member_ids = extract_bulk_member_ids(request.POST)
        target_members = {
            member.id: member
            for member in Member.objects.select_related("user").filter(id__in=member_ids).order_by("name", "id")
        }

        for member_id in member_ids:
            member = target_members.get(member_id)
            if member is None:
                continue
            login_key = f"login_id_{member.id}"
            password_key = f"password_{member.id}"
            email_key = f"email_{member.id}"
            un_activity_code_key = f"un_activity_code_{member.id}"
            auth_login_id = (request.POST.get(login_key) or "").strip()
            auth_password = (request.POST.get(password_key) or "").strip()
            email_value = (request.POST.get(email_key) or "").strip()
            un_activity_code_value = (request.POST.get(un_activity_code_key) or "").strip()
            row_login_inputs[member.id] = auth_login_id
            row_email_inputs[member.id] = email_value
            row_un_activity_code_inputs[member.id] = un_activity_code_value
            errors = []

            if not auth_login_id and not auth_password and not email_value and not un_activity_code_value:
                continue

            linked_user = member.user
            changed = False

            if email_value:
                try:
                    validate_email(email_value)
                except ValidationError:
                    errors.append("メールアドレスの形式が正しくありません。")
            if un_activity_code_value:
                if len(un_activity_code_value) != 5 or not un_activity_code_value.isdigit():
                    errors.append("UN活動コードは5桁の数字で入力してください。")
                else:
                    duplicate_code = Member.objects.filter(un_activity_code=un_activity_code_value).exclude(id=member.id)
                    if duplicate_code.exists():
                        errors.append("このUN活動コードはすでに使用されています。")

            if linked_user:
                if auth_login_id:
                    duplicate_user = User.objects.filter(username=auth_login_id).exclude(id=linked_user.id)
                    if duplicate_user.exists():
                        errors.append("このログインIDはすでに使用されています。")
                    elif linked_user.username != auth_login_id:
                        linked_user.username = auth_login_id
                        linked_user.save(update_fields=["username"])
                        changed = True
                if auth_password:
                    linked_user.set_password(auth_password)
                    linked_user.save(update_fields=["password"])
                    changed = True
            elif auth_login_id or auth_password:
                if auth_password and not auth_login_id:
                    errors.append("新規連携時はログインIDとパスワードを両方入力してください。")
                elif auth_login_id and not auth_password:
                    errors.append("新規連携時はログインIDとパスワードを両方入力してください。")
                else:
                    if User.objects.filter(username=auth_login_id).exists():
                        errors.append("このログインIDはすでに使用されています。")
                    else:
                        linked_user = User.objects.create_user(
                            username=auth_login_id,
                            password=auth_password,
                        )
                        member.user = linked_user
                        member.save(update_fields=["user"])
                        changed = True

            if not errors and member.email != email_value:
                member.email = email_value
                member.save(update_fields=["email"])
                changed = True
            if not errors and un_activity_code_value and member.un_activity_code != un_activity_code_value:
                member.un_activity_code = un_activity_code_value
                member.save(update_fields=["un_activity_code"])
                changed = True

            if errors:
                row_errors[member.id] = errors
            elif changed:
                updated_count += 1

        if not row_errors:
            return _member_settings_redirect(f"{updated_count}件のログイン情報を更新しました。")
        else:
            status_message = "入力内容にエラーがあります。該当行を修正してください。"
        page_obj = paginator.get_page(request.POST.get("page") or "1")

    member_rows = []
    for member in page_obj.object_list:
        member_rows.append(build_member_row_payload(
            member,
            login_input=row_login_inputs.get(member.id, ""),
            email_input=row_email_inputs.get(member.id, member.email or ""),
            un_activity_code_input=row_un_activity_code_inputs.get(member.id, member.un_activity_code or ""),
            errors=row_errors.get(member.id, []),
        ))

    context = {
        "page_obj": page_obj,
        "paginator": paginator,
        "status_message": status_message,
        "member_rows": member_rows,
        "current_page_number": str(page_obj.number),
        "query": query,
        "departments": Department.objects.filter(is_active=True).order_by("code"),
        "selected_department_ids": [str(value) for value in selected_department_ids],
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "rows_html": render_to_string("dashboard/partials/member_auth_bulk_rows.html", context, request=request),
                "has_next": page_obj.has_next(),
                "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
                "page_number": page_obj.number,
            }
        )
    return render(request, "dashboard/member_auth_bulk_settings.html", context)
