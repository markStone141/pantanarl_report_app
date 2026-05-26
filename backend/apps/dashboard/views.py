import logging
import re
from urllib.parse import urlencode
from datetime import timedelta

from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
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
from apps.targets.models import TargetMetric

from .forms import DepartmentForm, MemberRegistrationForm, TargetMetricForm
from .services.mail_actuals import (
    merge_adjustment_totals_into_department_totals,
    merge_adjustment_totals_into_member_totals,
)
from .services.target_progress import build_target_scope_snapshot, collect_metrics_by_code

User = get_user_model()
logger = logging.getLogger(__name__)


def _format_amount_text(value):
    if isinstance(value, int):
        return f"{value:,}"
    return value


def _mail_period_heading(period_name: str) -> str:
    match = re.search(r"第\d+次路程", period_name or "")
    return match.group(0) if match else (period_name or "-")


def _format_adjustment_breakdown(*, code: str, totals: dict) -> str:
    count = int(totals.get("count") or 0)
    amount = int(totals.get("amount") or 0)
    cs_count = int(totals.get("cs_count") or 0)
    refugee_count = int(totals.get("refugee_count") or 0)
    if not any([count, amount, cs_count, refugee_count]):
        return ""
    if code == "WV":
        return f"補正 CS{cs_count}件 / 難民{refugee_count}件 / 金額{amount:,}円"
    return f"補正 件数{count}件 / 金額{amount:,}円"


def _append_adjustment_note(*, base_text: str, code: str, totals: dict) -> str:
    note = _format_adjustment_breakdown(code=code, totals=totals)
    if not note:
        return base_text
    return f"{base_text}（{note}込み）"


def _dashboard_index_impl(request: HttpRequest) -> HttpResponse:
    real_today = timezone.localdate()
    selected_mode = "prev" if request.GET.get("mode") == "prev" else "today"
    today = real_today - timedelta(days=1) if selected_mode == "prev" else real_today
    target_department_objects = list(Department.objects.filter(is_active=True).order_by("code"))
    target_departments = [(department.code, department.name) for department in target_department_objects]
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

    metrics_by_code = collect_metrics_by_code(target_codes=target_codes)
    target_scope = build_target_scope_snapshot(
        target_date=today,
        target_codes=target_codes,
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
    for code, label in target_departments:
        month_target_text, month_actual_text, month_rate_text = format_metric_triples(
            metrics=metrics_by_code[code],
            target_values=month_target_values_by_code.get(code, {}),
            actual_totals=month_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        period_target_text, period_actual_text, period_rate_text = format_metric_triples(
            metrics=metrics_by_code[code],
            target_values=period_target_values_by_code.get(code, {}),
            actual_totals=period_actual_totals_by_code.get(code, {"count": 0, "amount": 0}),
        )
        target_progress_rows.append(
            {
                "label": label,
                "month_target": month_target_text,
                "month_actual": _append_adjustment_note(
                    base_text=month_actual_text,
                    code=code,
                    totals=month_adjustment_totals_by_code.get(code, {}),
                ),
                "month_rate": month_rate_text,
                "period_target": period_target_text,
                "period_actual": _append_adjustment_note(
                    base_text=period_actual_text,
                    code=code,
                    totals=period_adjustment_totals_by_code.get(code, {}),
                ),
                "period_rate": period_rate_text,
            }
        )

    kpi_cards = []
    for code, label in target_departments:
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

    label_by_code = {code: label for code, label in target_departments}

    def build_mail_template_payload(base_date):
        base_snapshot = build_submission_snapshot(
            report_date=base_date,
            target_departments=target_departments,
        )
        base_daily_totals = merge_adjustment_totals_into_department_totals(
            base_daily_totals=base_snapshot["daily_totals"],
            report_date=base_date,
            target_codes=target_codes,
        )
        base_member_totals = merge_adjustment_totals_into_member_totals(
            base_member_totals=base_snapshot["member_totals"],
            report_date=base_date,
            target_codes=target_codes,
        )
        base_has_report_by_code = base_snapshot["has_report_by_code"]

        base_scope = build_target_scope_snapshot(
            target_date=base_date,
            target_codes=target_codes,
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
        base_period_name = _mail_period_heading(base_scope["period_label"])
        base_period_range = base_scope["period_range"]

        def build_remaining_values(detail_rows):
            remaining_count = 0
            remaining_cs_count = 0
            remaining_refugee_count = 0
            remaining_amount = 0

            def _is_amount(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return (
                    code_text == "amount"
                    or "amount" in code_text
                    or "yen" in code_text
                    or "money" in code_text
                    or "support" in code_text
                    or "followup" in code_text
                    or "kingaku" in code_text
                    or "円" in unit_text
                )

            def _is_cs_count(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return "cs" in code_text or "cs" in unit_text

            def _is_refugee_count(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return "refugee" in code_text or "nanmin" in code_text or "難民" in unit_text

            def _is_count(code: str, unit: str) -> bool:
                code_text = (code or "").lower()
                unit_text = unit or ""
                return (
                    code_text == "count"
                    or "count" in code_text
                    or "kensu" in code_text
                    or "case" in code_text
                    or "num" in code_text
                    or "cs" in code_text
                    or "refugee" in code_text
                    or "nanmin" in code_text
                    or "件" in unit_text
                )

            for row in detail_rows:
                target = row.get("target") or 0
                actual = row.get("actual") or 0
                delta = target - actual
                code = row.get("code") or ""
                unit = row.get("unit") or ""
                if _is_amount(code, unit):
                    remaining_amount += delta
                elif _is_cs_count(code, unit):
                    remaining_cs_count += delta
                    remaining_count += delta
                elif _is_refugee_count(code, unit):
                    remaining_refugee_count += delta
                    remaining_count += delta
                elif _is_count(code, unit):
                    remaining_count += delta

            def _signed_count_text(value: int) -> str:
                if value < 0:
                    return f"+{abs(value)}件"
                return f"{value}件"

            def _signed_yen_text(value: int) -> str:
                if value < 0:
                    return f"+{abs(value):,}円"
                return f"{value:,}円"

            return {
                "count": remaining_count,
                "cs_count": remaining_cs_count,
                "refugee_count": remaining_refugee_count,
                "amount": remaining_amount,
                "text": f"{_signed_count_text(remaining_count)}/{_signed_yen_text(remaining_amount)}",
                "split_text": (
                    f"CS{_signed_count_text(remaining_cs_count)} "
                    f"難民{_signed_count_text(remaining_refugee_count)}/"
                    f"{_signed_yen_text(remaining_amount)}"
                ),
            }

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
                for row in build_member_rows(member_totals=base_member_totals, codes=[code])
            ]
            month_metric_lines = [
                f"{row['label']} {row['actual_text']}/{row['target_text']}{row['unit']} 達成率{row['rate']}"
                for row in base_metric_detail_by_code.get(code, {}).get("month", [])
            ]
            month_adjustment_note = _format_adjustment_breakdown(
                code=code,
                totals=base_month_adjustment_totals_by_code.get(code, {}),
            )
            if month_adjustment_note:
                month_metric_lines.append(month_adjustment_note)
            period_metric_lines = [
                f"{row['label']} {row['actual_text']}/{row['target_text']}{row['unit']} 達成率{row['rate']}"
                for row in base_metric_detail_by_code.get(code, {}).get("period", [])
            ]
            period_adjustment_note = _format_adjustment_breakdown(
                code=code,
                totals=base_period_adjustment_totals_by_code.get(code, {}),
            )
            if period_adjustment_note:
                period_metric_lines.append(period_adjustment_note)
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


def _member_form(*, data=None, initial=None) -> MemberRegistrationForm:
    form = MemberRegistrationForm(data=data, initial=initial)
    active_departments = Department.objects.filter(is_active=True)
    form.fields["departments"].queryset = active_departments
    form.fields["default_department"].queryset = active_departments
    form.fields["auth_login_id"].widget.attrs["placeholder"] = ""
    return form


def _member_form_initial(member: Member) -> dict:
    return {
        "name": member.name,
        "email": member.email,
        "departments": list(member.department_links.values_list("department_id", flat=True)),
        "default_department": member.default_department_id,
        "auth_login_id": member.user.username if member.user else "",
    }


def _save_member_form(*, form: MemberRegistrationForm, member: Member | None = None) -> tuple[Member | None, str | None]:
    if not form.is_valid():
        return None, None

    departments = form.cleaned_data["departments"]
    default_department = form.cleaned_data["default_department"]
    member_name = form.cleaned_data["name"].strip()
    member_email = (form.cleaned_data.get("email") or "").strip()
    auth_login_id = (form.cleaned_data.get("auth_login_id") or "").strip()
    auth_password = (form.cleaned_data.get("auth_password") or "").strip()
    linked_user = member.user if member else None

    if default_department and default_department not in departments:
        form.add_error("default_department", "メイン部署は所属部署から選択してください。")
        return None, None

    if member:
        member.name = member_name
        member.email = member_email
        member.default_department = default_department
        if auth_password and not auth_login_id and not linked_user:
            form.add_error("auth_login_id", "パスワードを設定する場合はログインIDを入力してください。")
            return None, None
        if auth_login_id:
            duplicate_user = User.objects.filter(username=auth_login_id)
            if linked_user:
                duplicate_user = duplicate_user.exclude(id=linked_user.id)
            if duplicate_user.exists():
                form.add_error("auth_login_id", "このログインIDはすでに使用されています。")
                return None, None
            if not linked_user:
                if not auth_password:
                    form.add_error("auth_password", "新規連携時はパスワードを入力してください。")
                    return None, None
                linked_user = User.objects.create_user(
                    username=auth_login_id,
                    password=auth_password,
                )
            else:
                linked_user.username = auth_login_id
                linked_user.save(update_fields=["username"])
        if linked_user and auth_password:
            linked_user.set_password(auth_password)
            linked_user.save(update_fields=["password"])
        member.user = linked_user
        member.save(update_fields=["name", "email", "user", "default_department"])
        status_message = f"{member.name} を更新しました。"
    else:
        if auth_login_id and not auth_password:
            form.add_error("auth_password", "新規作成時、ログインIDを設定する場合はパスワードが必要です。")
            return None, None
        if auth_password and not auth_login_id:
            form.add_error("auth_login_id", "パスワードを設定する場合はログインIDを入力してください。")
            return None, None
        if auth_login_id and User.objects.filter(username=auth_login_id).exists():
            form.add_error("auth_login_id", "このログインIDはすでに使用されています。")
            return None, None
        if auth_login_id:
            linked_user = User.objects.create_user(
                username=auth_login_id,
                password=auth_password,
            )
        member = Member.objects.create(
            name=member_name,
            email=member_email,
            user=linked_user,
            default_department=default_department,
        )
        status_message = f"{member.name} を登録しました。"

    MemberDepartment.objects.filter(member=member).exclude(department__in=departments).delete()
    existing_departments = set(MemberDepartment.objects.filter(member=member).values_list("department_id", flat=True))
    for dept in departments:
        if dept.id not in existing_departments:
            MemberDepartment.objects.create(member=member, department=dept)
    return member, status_message


def _build_member_settings_queryset(*, query: str, sort: str, active_only: bool, missing_email_only: bool, missing_login_only: bool):
    members_qs = (
        Member.objects.prefetch_related("department_links__department")
        .select_related("default_department")
        .select_related("user")
    )
    if active_only:
        members_qs = members_qs.filter(is_active=True)
    if missing_email_only:
        members_qs = members_qs.filter(Q(email__isnull=True) | Q(email=""))
    if missing_login_only:
        members_qs = members_qs.filter(user__isnull=True)
    if query:
        members_qs = members_qs.filter(
            Q(name__icontains=query)
            | Q(email__icontains=query)
            | Q(user__username__icontains=query)
            | Q(default_department__name__icontains=query)
            | Q(default_department__code__icontains=query)
            | Q(department_links__department__name__icontains=query)
            | Q(department_links__department__code__icontains=query)
        ).distinct()

    if sort == "oldest":
        ordering = ("id",)
    elif sort == "newest":
        ordering = ("-id",)
    elif sort == "department":
        ordering = ("default_department__code", "name", "id")
    else:
        ordering = ("name", "id")
    return members_qs.order_by(*ordering)


def _member_settings_redirect(status_message: str) -> HttpResponse:
    return redirect(f"{reverse('member_settings')}?{urlencode({'status': status_message})}")


def _build_member_row_payload(member: Member, *, login_input: str = "", email_input: str | None = None, errors: list[str] | None = None):
    return {
        "member": member,
        "login_input": login_input,
        "email_input": member.email if email_input is None else email_input,
        "errors": errors or [],
    }


def _build_member_bulk_queryset(*, query: str):
    members_qs = Member.objects.select_related("user").order_by("name", "id")
    if query:
        members_qs = members_qs.filter(
            Q(name__icontains=query)
            | Q(email__icontains=query)
            | Q(user__username__icontains=query)
        ).distinct()
    return members_qs


def _extract_bulk_member_ids(post_data) -> list[int]:
    member_ids = set()
    prefixes = ("login_id_", "password_", "email_")
    for key in post_data.keys():
        for prefix in prefixes:
            if key.startswith(prefix):
                raw_id = key[len(prefix):]
                if raw_id.isdigit():
                    member_ids.add(int(raw_id))
                break
    return sorted(member_ids)


def _department_form(*, data=None, initial=None, edit_department=None) -> DepartmentForm:
    form = DepartmentForm(data=data, initial=initial)
    if edit_department:
        reporter_ids = Member.objects.active().filter(
            department_links__department=edit_department,
        ).values_list("id", flat=True)
        form.fields["default_reporter"].queryset = Member.objects.active().filter(
            id__in=reporter_ids,
        ).order_by("name")
    else:
        form.fields["default_reporter"].queryset = Member.objects.none()
    return form


def _target_metric_form(*, data=None, initial=None) -> TargetMetricForm:
    return TargetMetricForm(data=data, initial=initial)


@require_roles(ROLE_ADMIN)
def member_delete(request: HttpRequest, member_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("member_settings")

    member = get_object_or_404(Member, id=member_id)
    linked_user = member.user
    member.is_active = not member.is_active
    member.save(update_fields=["is_active"])
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
    if metric_department_id and metric_department_id.isdigit():
        selected_metric_department = Department.objects.filter(id=int(metric_department_id)).first()
    if not selected_metric_department:
        selected_metric_department = edit_department or Department.objects.order_by("code").first()

    form = _department_form(
        initial={
            "name": edit_department.name,
            "code": edit_department.code,
            "default_reporter": edit_department.default_reporter_id,
        }
        if edit_department
        else None,
        edit_department=edit_department,
    )
    metric_form = _target_metric_form(initial={"display_order": 1, "is_active": True})

    edit_metric_id = request.GET.get("edit_metric")
    if edit_metric_id and edit_metric_id.isdigit() and selected_metric_department:
        edit_metric = TargetMetric.objects.filter(
            id=int(edit_metric_id),
            department=selected_metric_department,
        ).first()
        if edit_metric:
            metric_form = _target_metric_form(
                initial={
                    "label": edit_metric.label,
                    "code": edit_metric.code,
                    "unit": edit_metric.unit,
                    "display_order": edit_metric.display_order,
                    "is_active": edit_metric.is_active,
                }
            )

    if request.method == "POST":
        action = request.POST.get("action") or "save_department"
        if action == "save_department":
            edit_department_id = request.POST.get("edit_department_id")
            if edit_department_id and edit_department_id.isdigit():
                edit_department = Department.objects.filter(id=int(edit_department_id)).first()
            form = _department_form(data=request.POST, edit_department=edit_department)
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
                            department.save(update_fields=["name", "code", "default_reporter"])
                            status_message = f"{department.name}（{department.code}）を更新しました。"
                            edit_department = None
                            form = _department_form()
                    else:
                        department = Department.objects.create(
                            name=form.cleaned_data["name"].strip(),
                            code=code,
                            default_reporter=None,
                            is_active=True,
                        )
                        status_message = f"{department.name}（{department.code}）を追加しました。"
                        edit_department = None
                        form = _department_form()

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
            metric_form = _target_metric_form(data=request.POST)
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
                    metric_form = _target_metric_form(initial={"display_order": 1, "is_active": True})
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
    members_qs = _build_member_settings_queryset(
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
        form = _member_form(data=request.POST)
        member, status_message = _save_member_form(form=form)
        if member and not form.errors:
            form = _member_form()
    else:
        form = _member_form()
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
        form = _member_form(data=request.POST)
        saved_member, status_message = _save_member_form(form=form, member=member)
        if saved_member and not form.errors:
            return _member_settings_redirect(status_message)
    else:
        form = _member_form(initial=_member_form_initial(member))
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
    members_qs = _build_member_bulk_queryset(query=query)
    paginator = Paginator(members_qs, 20)
    current_page_number = request.GET.get("page") or "1"
    page_obj = paginator.get_page(current_page_number)
    status_message = None
    row_errors = {}
    row_login_inputs = {}
    row_email_inputs = {}

    if request.method == "POST":
        updated_count = 0
        member_ids = _extract_bulk_member_ids(request.POST)
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
            auth_login_id = (request.POST.get(login_key) or "").strip()
            auth_password = (request.POST.get(password_key) or "").strip()
            email_value = (request.POST.get(email_key) or "").strip()
            row_login_inputs[member.id] = auth_login_id
            row_email_inputs[member.id] = email_value
            errors = []

            if not auth_login_id and not auth_password and not email_value:
                continue

            linked_user = member.user
            changed = False

            if email_value:
                try:
                    validate_email(email_value)
                except ValidationError:
                    errors.append("メールアドレスの形式が正しくありません。")

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
        member_rows.append(_build_member_row_payload(
            member,
            login_input=row_login_inputs.get(member.id, ""),
            email_input=row_email_inputs.get(member.id, member.email or ""),
            errors=row_errors.get(member.id, []),
        ))

    context = {
        "page_obj": page_obj,
        "paginator": paginator,
        "status_message": status_message,
        "member_rows": member_rows,
        "current_page_number": str(page_obj.number),
        "query": query,
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
