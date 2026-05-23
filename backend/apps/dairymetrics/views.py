import json
from datetime import date

from django.contrib.auth import login as auth_login, logout as auth_logout
from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Department, Member
from apps.mail.models import MailRecipientGroup, MailSendHistory
from apps.mail.services import record_transaction_mail_failure, send_transaction_mail_mock
from apps.targets.models import Period

from .auth import get_member_profile, require_dairymetrics_admin, require_dairymetrics_member
from .forms import (
    DairyMetricsLoginForm,
    DairymetricsV2CloseoutForm,
    DairymetricsV2DepartmentTargetForm,
    DairymetricsV2PersonalSetupForm,
    DairymetricsV2TransactionForm,
    MemberDailyMetricEntryForm,
    MemberScopeTargetForm,
    MetricAdjustmentForm,
)
from .models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction, MetricAdjustment
from .services.entry_v2 import (
    build_transaction_mail_preview,
    build_v2_department_activity_rows,
    build_v2_redirect_url,
    entry_count_breakdown_text,
    entry_total_count,
    get_default_mail_group,
    get_month_target_amount,
    get_or_create_department_daily_summary,
    get_period_target_amount,
    get_previous_department_target_amount,
    get_previous_personal_targets,
    is_wv_department,
    transaction_result_type_label,
    transaction_mail_status,
)
from .services.metrics_v2 import build_metrics_v2_dashboard_payload, resolve_metrics_v2_scope
from .selectors import (
    build_admin_daily_overview,
    build_admin_ranking_overview,
    build_admin_month_comparison,
    build_admin_month_overview,
    build_member_daily_overview,
    build_member_month_overview,
    build_member_to_member_comparison,
    build_member_dashboard,
    build_member_ranking_detail,
)


INLINE_ADJUSTMENT_NOTE = "__inline_monthly_adjustment__"
ENTRY_V2_AGE_BANDS = [
    {"key": "teens", "label": "10代"},
    {"key": "twenties", "label": "20代"},
    {"key": "thirties", "label": "30代"},
    {"key": "forties", "label": "40代"},
    {"key": "fifties", "label": "50代"},
    {"key": "sixties", "label": "60代"},
    {"key": "seventies", "label": "70代"},
    {"key": "eighties", "label": "80代"},
    {"key": "nineties_or_older", "label": "90代以上"},
]
ENTRY_V2_GENDER_BANDS = [
    {"key": "male", "label": "男性"},
    {"key": "female", "label": "女性"},
]
ENTRY_V2_NATIONALITY_BANDS = [
    {"key": "domestic", "label": "国内"},
    {"key": "overseas", "label": "海外"},
]
ENTRY_V2_TARGET_COUNT_OPTIONS = [1, 2, 3, 4, 5]
ENTRY_V2_TARGET_AMOUNT_OPTIONS = list(range(1000, 10001, 500))
ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS = list(range(1000, 5001, 500))


def _build_entry_form(*, member, data=None, department_code="", entry_date=None):
    entry_date = entry_date or timezone.localdate()
    instance = None
    if department_code:
        instance = MemberDailyMetricEntry.objects.filter(
            member=member,
            department__code=department_code,
            entry_date=entry_date,
        ).select_related("department").first()
    initial = {"entry_date": entry_date}
    if department_code and not instance:
        department = Department.objects.filter(
            is_active=True,
            code=department_code,
            member_links__member=member,
        ).first()
        if department:
            initial["department"] = department
    return MemberDailyMetricEntryForm(
        data=data,
        instance=instance,
        member=member,
        initial=initial,
    )


def _member_departments(member):
    return Department.objects.filter(is_active=True, member_links__member=member).distinct().order_by("code")


def _resolve_metrics_v2_department(*, request, member):
    requested_code = (request.GET.get("department") or "").strip()
    if request.user.is_staff:
        departments = list(Department.objects.filter(is_active=True).order_by("code"))
    else:
        departments = list(_member_departments(member))
    selected_department = None
    if requested_code:
        selected_department = next((department for department in departments if department.code == requested_code), None)
    if not selected_department:
        selected_department = next((department for department in departments if department.code == "UN"), None)
    if not selected_department and member and member.default_department_id:
        selected_department = next((department for department in departments if department.id == member.default_department_id), None)
    if not selected_department and departments:
        selected_department = departments[0]
    return departments, selected_department


def _parse_month_input(raw_value: str) -> date | None:
    raw_value = (raw_value or "").strip()
    if len(raw_value) != 7:
        return None
    return parse_date(f"{raw_value}-01")


def _default_entry_department_code(*, member, departments, selected_department):
    if selected_department:
        return selected_department
    department_codes = [department.code for department in departments]
    if member.default_department and member.default_department.code in department_codes:
        return member.default_department.code
    return department_codes[0] if department_codes else ""


def _build_entry_v2_demo_context(*, member, selected_department, entry_date):
    departments = list(_member_departments(member))
    selected_department_code = _default_entry_department_code(
        member=member,
        departments=departments,
        selected_department=selected_department,
    )
    existing_entry = None
    if selected_department_code:
        existing_entry = (
            MemberDailyMetricEntry.objects.filter(
                member=member,
                department__code=selected_department_code,
                entry_date=entry_date,
            )
            .select_related("department")
            .first()
        )
    initial_count = 0
    initial_amount = 0
    if existing_entry:
        initial_count = entry_total_count(existing_entry)
        initial_amount = int(existing_entry.support_amount or 0)
    return {
        "member": member,
        "departments": departments,
        "selected_department_code": selected_department_code,
        "entry_date": entry_date,
        "initial_total_count": initial_count,
        "initial_total_amount": initial_amount,
        "age_bands": ENTRY_V2_AGE_BANDS,
        "gender_bands": ENTRY_V2_GENDER_BANDS,
        "nationality_bands": ENTRY_V2_NATIONALITY_BANDS,
        "is_admin": False,
        "demo_mode": True,
    }


def _build_demo_progress_card(*, label, current_amount, target_amount, helper_text="", target_source=""):
    current_amount = int(current_amount or 0)
    target_amount = int(target_amount or 0)
    remaining_amount = max(target_amount - current_amount, 0) if target_amount else 0
    achievement_rate = round((current_amount / target_amount) * 100, 1) if target_amount else None
    return {
        "label": label,
        "current_amount": current_amount,
        "target_amount": target_amount,
        "remaining_amount": remaining_amount,
        "achievement_rate": achievement_rate,
        "helper_text": helper_text,
        "target_source": target_source,
        "has_target": bool(target_amount),
        "is_complete": bool(target_amount) and current_amount >= target_amount,
    }

def _first_non_empty_line(text):
    if not text:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _build_entry_v2_transaction_demo_context(
    *,
    member,
    selected_department,
    entry_date,
    personal_setup_form=None,
    department_target_form=None,
    transaction_form=None,
    closeout_form=None,
    status_message="",
    open_entry_panel=False,
    open_personal_target_panel=False,
    open_department_target_panel=False,
    open_closeout_panel=False,
    preview_transaction=None,
):
    base_context = _build_entry_v2_demo_context(
        member=member,
        selected_department=selected_department,
        entry_date=entry_date,
    )
    selected_department_code = base_context["selected_department_code"]
    selected_department_obj = next(
        (department for department in base_context["departments"] if department.code == selected_department_code),
        None,
    )
    existing_entry = None
    department_summary = None
    if selected_department_obj:
        existing_entry = (
            MemberDailyMetricEntry.objects.filter(
                member=member,
                department=selected_department_obj,
                entry_date=entry_date,
            )
            .select_related("department")
            .prefetch_related("transactions__mail_send_histories")
            .first()
        )
        department_summary = DepartmentDailyMetricSummary.objects.filter(
            department=selected_department_obj,
            entry_date=entry_date,
        ).select_related("department", "created_by", "updated_by").first()

    previous_personal_target_count = 1
    previous_personal_target_amount = 3000
    previous_personal_target_cs_count = 0
    previous_personal_target_refugee_count = 1
    previous_department_target_amount = 10000
    if selected_department_obj:
        (
            previous_personal_target_count,
            previous_personal_target_amount,
            previous_personal_target_cs_count,
            previous_personal_target_refugee_count,
        ) = get_previous_personal_targets(
            member=member,
            department=selected_department_obj,
            entry_date=entry_date,
        )
        previous_department_target_amount = get_previous_department_target_amount(
            department=selected_department_obj,
            entry_date=entry_date,
        )

    personal_target_count = int(getattr(existing_entry, "daily_target_count", 0) or 0)
    personal_target_amount = int(getattr(existing_entry, "daily_target_amount", 0) or 0)
    personal_target_cs_count = int(getattr(existing_entry, "daily_target_cs_count", 0) or 0)
    personal_target_refugee_count = int(getattr(existing_entry, "daily_target_refugee_count", 0) or 0)
    personal_total_count = entry_total_count(existing_entry)
    personal_total_amount = int(getattr(existing_entry, "support_amount", 0) or 0)
    current_location_name = getattr(existing_entry, "location_name", "") or ""
    department_day_total = int(getattr(department_summary, "support_amount", 0) or 0)
    department_day_target = int(getattr(department_summary, "daily_target_amount", 0) or 0)

    active_period = (
        Period.objects.filter(start_date__lte=entry_date, end_date__gte=entry_date)
        .order_by("-start_date", "-id")
        .first()
    )
    period_target_amount = 0
    period_total_amount = 0
    period_label = "保存済み路程がありません"
    period_target_source = ""
    if active_period and selected_department_obj:
        period_label = active_period.name
        period_target_amount, has_period_target = get_period_target_amount(
            period=active_period,
            department=selected_department_obj,
        )
        period_total_amount = int(
            MemberDailyMetricEntry.objects.filter(
                department=selected_department_obj,
                entry_date__gte=active_period.start_date,
                entry_date__lte=active_period.end_date,
            ).aggregate(total=Sum("support_amount"))["total"]
            or 0
        )
        if has_period_target:
            period_target_source = f"{selected_department_obj.code} の保存済み路程目標"

    month_target_amount = 0
    month_total_amount = 0
    month_target_source = ""
    month_label = entry_date.strftime("%Y年%m月")
    if selected_department_obj:
        month_target_amount, has_month_target = get_month_target_amount(
            department=selected_department_obj,
            target_month=entry_date.replace(day=1),
        )
        month_total_amount = int(
            MemberDailyMetricEntry.objects.filter(
                department=selected_department_obj,
                entry_date__year=entry_date.year,
                entry_date__month=entry_date.month,
            ).aggregate(total=Sum("support_amount"))["total"]
            or 0
        )
        if has_month_target:
            month_target_source = f"{selected_department_obj.code} の保存済み月目標"

    progress_cards = [
        _build_demo_progress_card(
            label="個人の日目標",
            current_amount=personal_total_amount,
            target_amount=personal_target_amount,
            helper_text=f"{member.name}さんの当日累計",
            target_source="本人の日目標" if personal_target_amount or personal_target_count else "",
        ),
        _build_demo_progress_card(
            label="全体の日目標",
            current_amount=department_day_total,
            target_amount=department_day_target,
            helper_text=f"{selected_department_code or '-'} の当日累計",
            target_source="部署全体の日目標" if department_day_target else "",
        ),
        _build_demo_progress_card(
            label="路程目標",
            current_amount=period_total_amount,
            target_amount=period_target_amount,
            helper_text=period_label,
            target_source=period_target_source,
        ),
        _build_demo_progress_card(
            label="月目標",
            current_amount=month_total_amount,
            target_amount=month_target_amount,
            helper_text=month_label,
            target_source=month_target_source,
        ),
    ]

    transactions = []
    default_mail_group = None
    if existing_entry:
        default_mail_group = get_default_mail_group(department=selected_department_obj)
        latest_histories_by_transaction_id = {}
        for tx in existing_entry.transactions.all():
            non_test_histories = [history for history in tx.mail_send_histories.all() if not history.is_test]
            non_test_histories.sort(
                key=lambda history: (
                    history.last_attempt_at is not None,
                    history.last_attempt_at or history.created_at,
                    history.sent_at is not None,
                    history.sent_at or history.created_at,
                    history.created_at,
                    history.id,
                ),
                reverse=True,
            )
            latest_histories_by_transaction_id[tx.id] = non_test_histories[0] if non_test_histories else None
        for tx in existing_entry.transactions.all():
            latest_history = latest_histories_by_transaction_id.get(tx.id)
            if latest_history and latest_history.status == MailSendHistory.STATUS_FAILED:
                mail_status = "送信失敗"
            elif latest_history and latest_history.status == MailSendHistory.STATUS_SENT:
                if latest_history.sent_at and tx.updated_at and tx.updated_at > latest_history.sent_at:
                    mail_status = "修正済み未送信"
                elif latest_history.is_resend:
                    mail_status = "修正再送済み"
                else:
                    mail_status = "送信済み"
            else:
                mail_status = "未送信"
            preview_payload = build_transaction_mail_preview(
                member=member,
                department_code=selected_department_code,
                transaction_obj=tx,
                progress_cards=progress_cards,
            )
            transactions.append(
                {
                    "id": tx.id,
                    "time_label": timezone.localtime(tx.created_at).strftime("%H:%M"),
                    "amount": tx.support_amount,
                    "amount_value": tx.support_amount,
                    "age_band": tx.get_age_band_display(),
                    "age_band_value": tx.age_band,
                    "is_student": tx.is_student,
                    "gender": tx.get_gender_display(),
                    "gender_value": tx.gender,
                    "nationality": tx.get_nationality_type_display(),
                    "nationality_value": tx.nationality_type,
                    "result_type_label": transaction_result_type_label(tx),
                    "result_type_value": tx.wv_result_type,
                    "wv_cs_count": int(tx.wv_cs_count or 0),
                    "wv_refugee_amount": int(tx.wv_refugee_amount or 0),
                    "location": tx.location,
                    "comment": tx.comment,
                    "mail_status": mail_status,
                    "has_mail_history": bool(latest_history),
                    "preview_subject": preview_payload["subject"],
                    "resend_preview_subject": (
                        f"{preview_payload['subject']}（再送）"
                        if latest_history and not preview_payload["subject"].endswith("（再送）")
                        else preview_payload["subject"]
                    ),
                    "preview_body": preview_payload["body"],
                    "latest_history_id": latest_history.id if latest_history else "",
                    "latest_history_subject": latest_history.subject_snapshot if latest_history else "",
                    "latest_history_body": latest_history.body_snapshot if latest_history else "",
                    "mail_error_message": (
                        latest_history.error_message
                        if latest_history and latest_history.status == MailSendHistory.STATUS_FAILED
                        else ""
                    ),
                }
            )

    sent_mail_histories = []
    available_mail_groups = []
    department_activity_rows = {"active": [], "closed": []}
    if selected_department_obj:
        department_activity_rows = build_v2_department_activity_rows(
            department=selected_department_obj,
            entry_date=entry_date,
        )
        available_mail_groups = list(
            MailRecipientGroup.objects.filter(is_active=True)
            .filter(department=selected_department_obj)
            .order_by("name")
        )
        if not available_mail_groups:
            available_mail_groups = list(
                MailRecipientGroup.objects.filter(is_active=True, department__isnull=True).order_by("name")
            )
        sent_mail_qs = MailSendHistory.objects.filter(
            department=selected_department_obj,
            activity_date=entry_date,
            status=MailSendHistory.STATUS_SENT,
            is_test=False,
        ).select_related("recipient_group", "transaction", "sender_member")
        for history in sent_mail_qs:
            sent_mail_histories.append(
                {
                    "id": history.id,
                    "sent_at": timezone.localtime(history.sent_at).strftime("%H:%M") if history.sent_at else "-",
                    "subject": history.subject_snapshot,
                    "sender_name": history.sender_member.name if history.sender_member else "送信者未設定",
                    "body": history.body_snapshot,
                    "amount": int(history.transaction.support_amount or 0) if history.transaction else 0,
                    "transaction_id": history.transaction_id or "",
                    "is_resend": history.is_resend,
                }
            )

    personal_setup_form = personal_setup_form or DairymetricsV2PersonalSetupForm(
        member=member,
        initial={
            "department": selected_department_obj,
            "entry_date": entry_date,
            "location_name": current_location_name,
            "daily_target_count": personal_target_count or previous_personal_target_count,
            "daily_target_cs_count": personal_target_cs_count or previous_personal_target_cs_count,
            "daily_target_refugee_count": personal_target_refugee_count or previous_personal_target_refugee_count,
            "daily_target_amount": personal_target_amount or previous_personal_target_amount,
        },
    )
    department_target_form = department_target_form or DairymetricsV2DepartmentTargetForm(
        initial={
            "entry_date": entry_date,
            "daily_target_amount": department_day_target or previous_department_target_amount,
        }
    )
    transaction_form = transaction_form or DairymetricsV2TransactionForm(
        department=selected_department_obj,
        initial={
            "support_amount": 3000,
            "wv_result_type": MemberMetricTransaction.WV_RESULT_CS,
            "wv_cs_count": 1,
            "wv_refugee_amount": 0,
            "location": current_location_name,
            "age_band": MemberMetricTransaction.AGE_BAND_SEVENTIES,
            "gender": MemberMetricTransaction.GENDER_FEMALE,
            "nationality_type": MemberMetricTransaction.NATIONALITY_DOMESTIC,
            "comment": "",
        }
    )
    closeout_form = closeout_form or DairymetricsV2CloseoutForm(
        instance=existing_entry,
        initial={
            "approach_count": getattr(existing_entry, "approach_count", 0),
            "communication_count": getattr(existing_entry, "communication_count", 0),
        },
    )

    preview_payload = None
    if preview_transaction:
        preview_payload = build_transaction_mail_preview(
            member=member,
            department_code=selected_department_code,
            transaction_obj=preview_transaction,
            progress_cards=progress_cards,
        )

    personal_target_count_value = str(personal_setup_form["daily_target_count"].value() or previous_personal_target_count)
    if "daily_target_cs_count" in personal_setup_form.fields:
        personal_target_cs_count_value = str(
            personal_setup_form["daily_target_cs_count"].value() or previous_personal_target_cs_count
        )
        personal_target_refugee_count_value = str(
            personal_setup_form["daily_target_refugee_count"].value() or previous_personal_target_refugee_count
        )
    else:
        personal_target_cs_count_value = "0"
        personal_target_refugee_count_value = "0"
    personal_target_amount_value = str(personal_setup_form["daily_target_amount"].value() or previous_personal_target_amount)
    personal_location_name_value = str(personal_setup_form["location_name"].value() or current_location_name)
    department_target_amount_value = str(department_target_form["daily_target_amount"].value() or previous_department_target_amount)
    transaction_amount_value = str(transaction_form["support_amount"].value() or "3000")
    transaction_wv_result_type_value = (
        transaction_form["wv_result_type"].value() if "wv_result_type" in transaction_form.fields else ""
    ) or MemberMetricTransaction.WV_RESULT_CS
    transaction_wv_cs_count_value = str(
        (transaction_form["wv_cs_count"].value() if "wv_cs_count" in transaction_form.fields else 1) or 1
    )
    transaction_wv_refugee_amount_value = str(
        (transaction_form["wv_refugee_amount"].value() if "wv_refugee_amount" in transaction_form.fields else 0) or 0
    )
    transaction_age_band_value = transaction_form["age_band"].value() or MemberMetricTransaction.AGE_BAND_SEVENTIES
    personal_entry_date_value = str(personal_setup_form["entry_date"].value() or entry_date.strftime("%Y-%m-%d"))
    department_entry_date_value = str(department_target_form["entry_date"].value() or entry_date.strftime("%Y-%m-%d"))

    return {
        **base_context,
        "progress_cards": progress_cards,
        "transactions": transactions,
        "sent_mail_histories": sent_mail_histories,
        "department_activity_rows": department_activity_rows,
        "selected_department_name": getattr(selected_department_obj, "name", selected_department_code),
        "department_summary": department_summary,
        "entry": existing_entry,
        "selected_department_is_wv": is_wv_department(selected_department_obj),
        "entry_count_breakdown_text": entry_count_breakdown_text(existing_entry),
        "has_personal_target": bool(personal_target_amount or personal_target_count),
        "has_department_target": bool(department_day_target),
        "department_target_entry_date": entry_date,
        "personal_setup_form": personal_setup_form,
        "department_target_form": department_target_form,
        "transaction_form": transaction_form,
        "closeout_form": closeout_form,
        "status_message": status_message,
        "open_entry_panel": open_entry_panel,
        "open_personal_target_panel": open_personal_target_panel,
        "open_department_target_panel": open_department_target_panel,
        "open_closeout_panel": open_closeout_panel,
        "preview_payload": preview_payload,
        "preview_transaction": preview_transaction,
        "default_mail_group": default_mail_group,
        "available_mail_groups": available_mail_groups,
        "target_count_options": ENTRY_V2_TARGET_COUNT_OPTIONS,
        "target_amount_options": ENTRY_V2_TARGET_AMOUNT_OPTIONS,
        "transaction_amount_options": ENTRY_V2_TRANSACTION_AMOUNT_OPTIONS,
        "personal_target_count_value": personal_target_count_value,
        "personal_target_cs_count_value": personal_target_cs_count_value,
        "personal_target_refugee_count_value": personal_target_refugee_count_value,
        "personal_target_amount_value": personal_target_amount_value,
        "personal_location_name_value": personal_location_name_value,
        "department_target_amount_value": department_target_amount_value,
        "transaction_amount_value": transaction_amount_value,
        "transaction_wv_result_type_value": transaction_wv_result_type_value,
        "transaction_wv_cs_count_value": transaction_wv_cs_count_value,
        "transaction_wv_refugee_amount_value": transaction_wv_refugee_amount_value,
        "personal_entry_date_value": personal_entry_date_value,
        "department_entry_date_value": department_entry_date_value,
        "current_location_name": current_location_name,
        "show_student_field": transaction_age_band_value
        in {
            MemberMetricTransaction.AGE_BAND_TEENS,
            MemberMetricTransaction.AGE_BAND_TWENTIES,
        },
    }


def _login_redirect_url(user, *, fallback=""):
    if fallback:
        return fallback
    if user.is_staff:
        return reverse("dairymetrics_admin_overview")
    return reverse("dairymetrics_dashboard")


def _admin_monthly_allowed_fields(department):
    allowed_fields = {
        "approach_count": "number",
        "communication_count": "number",
        "support_amount": "number",
        "location_name": "text",
    }
    if department.code == "WV":
        allowed_fields.update({"cs_count": "number", "refugee_count": "number"})
    else:
        allowed_fields["result_count"] = "number"
    adjustment_fields = {
        "return_postal_count",
        "return_postal_amount",
        "return_qr_count",
        "return_qr_amount",
    }
    for field_name in adjustment_fields:
        allowed_fields[field_name] = "number"
    return allowed_fields, adjustment_fields


def _apply_admin_monthly_update(*, member, department, entry_date, field_name, raw_value):
    allowed_fields, adjustment_fields = _admin_monthly_allowed_fields(department)
    if field_name not in allowed_fields:
        return {"error": "invalid_field"}, 400

    if field_name in adjustment_fields:
        if raw_value == "":
            desired_value = 0
        else:
            try:
                desired_value = int(raw_value)
            except ValueError:
                return {"error": "invalid_value"}, 400
            if desired_value < 0:
                return {"error": "invalid_value"}, 400

        inline_adjustment, _ = MetricAdjustment.objects.get_or_create(
            member=member,
            department=department,
            target_date=entry_date,
            source_type=MetricAdjustment.SOURCE_OTHER,
            note=INLINE_ADJUSTMENT_NOTE,
        )
        other_total = (
            MetricAdjustment.objects.filter(
                member=member,
                department=department,
                target_date=entry_date,
            )
            .exclude(pk=inline_adjustment.pk)
            .aggregate(total=Sum(field_name))
            .get("total")
            or 0
        )
        if desired_value < other_total:
            return {"error": "value_below_existing_adjustments"}, 400
        setattr(inline_adjustment, field_name, desired_value - int(other_total))
        inline_adjustment.save()
        return {"ok": True}, 200

    if allowed_fields[field_name] == "text":
        normalized_value = raw_value
    else:
        if raw_value == "":
            normalized_value = 0
        else:
            try:
                normalized_value = int(raw_value)
            except ValueError:
                return {"error": "invalid_value"}, 400
            if normalized_value < 0:
                return {"error": "invalid_value"}, 400

    entry = MemberDailyMetricEntry.objects.filter(
        member=member,
        department=department,
        entry_date=entry_date,
    ).first()

    if entry is None:
        if allowed_fields[field_name] == "text" and normalized_value == "":
            return {"ok": True, "skipped": True}, 200
        if allowed_fields[field_name] == "number" and normalized_value == 0:
            return {"ok": True, "skipped": True}, 200
        entry = MemberDailyMetricEntry(
            member=member,
            department=department,
            entry_date=entry_date,
            input_source=MemberDailyMetricEntry.SOURCE_ADMIN,
        )

    if getattr(entry, field_name) == normalized_value:
        return {"ok": True, "skipped": True}, 200

    setattr(entry, field_name, normalized_value)
    if not entry.pk:
        entry.input_source = MemberDailyMetricEntry.SOURCE_ADMIN
    entry.save()
    return {"ok": True}, 200

def _member_directory_queryset():
    return (
        Member.objects.filter(department_links__department__is_active=True)
        .distinct()
        .order_by("name")
        .prefetch_related("department_links__department")
    )


def _build_member_directory():
    members = _member_directory_queryset()
    return [
        {
            "member": member,
            "departments": [link.department for link in member.department_links.all() if link.department.is_active],
        }
        for member in members
    ]


def _member_filter_departments(member_rows):
    departments_by_code = {}
    for row in member_rows:
        for department in row["departments"]:
            departments_by_code[department.code] = department
    return [departments_by_code[code] for code in sorted(departments_by_code)]


def _default_member_filter_code(viewer_member, filter_departments):
    department_codes = [department.code for department in filter_departments]
    if "UN" in department_codes:
        return "UN"
    if viewer_member:
        if viewer_member.default_department and viewer_member.default_department.code in department_codes:
            return viewer_member.default_department.code
        viewer_department = Department.objects.filter(is_active=True, member_links__member=viewer_member).order_by("code").first()
        if viewer_department and viewer_department.code in department_codes:
            return viewer_department.code
    return department_codes[0] if department_codes else ""

def _build_member_dashboard_context(*, request, member, readonly=False, viewer_member=None):
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
    selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
    selected_period_id = (request.GET.get("period_id") or "").strip()
    dashboard_data = build_member_dashboard(
        member,
        today=timezone.localdate(),
        department_code=selected_department_code,
        scope=selected_scope,
        start_date=selected_start_date,
        end_date=selected_end_date,
        period_id=selected_period_id or None,
    )
    selected_department = dashboard_data["selected_department"]
    entry_form = None
    scope_target_form = None
    scope_target_form_action = ""
    if not readonly:
        entry_form = _build_entry_form(
            member=member,
            department_code=selected_department.code if selected_department else "",
            entry_date=timezone.localdate(),
        )
    if not readonly and selected_department and dashboard_data["selected_card"]:
        selected_card = dashboard_data["selected_card"]
        if selected_card["scope"] in {"period", "month"}:
            scope_target_form = MemberScopeTargetForm(
                member=member,
                scope=selected_card["scope"],
                department=selected_department,
                period=selected_card.get("period_obj"),
                target_month=selected_card.get("month_start"),
            )
            scope_target_form_action = (
                f"{reverse('dairymetrics_scope_target')}?department={selected_department.code}&scope={selected_card['scope']}"
            )
    member_rows = _build_member_directory() if readonly else []
    member_filter_departments = _member_filter_departments(member_rows) if readonly else []
    context = {
        "page_title": "DairyMetrics",
        "member": member,
        "departments": dashboard_data["departments"],
        "selected_department": selected_department,
        "selected_card": dashboard_data["selected_card"],
        "scope_options": dashboard_data["scope_options"],
        "selected_scope": dashboard_data["selected_scope"],
        "entry_form": entry_form,
        "scope_target_form": scope_target_form,
        "scope_target_form_action": scope_target_form_action,
        "is_admin": request.user.is_staff,
        "readonly_dashboard": readonly,
        "viewer_member": viewer_member if readonly else (viewer_member or member),
        "member_rows": member_rows,
        "member_filter_departments": member_filter_departments,
        "member_filter_default_code": _default_member_filter_code(viewer_member, member_filter_departments) if readonly else "",
        "card_base_url": (
            reverse("dairymetrics_member_dashboard", args=[member.id])
            if readonly
            else reverse("dairymetrics_dashboard")
        ),
    }
    if readonly and viewer_member and member and viewer_member.id != member.id and dashboard_data["selected_card"]:
        start_date, end_date = _comparison_scope_bounds(
            dashboard_data["selected_card"],
            today=timezone.localdate(),
        )
        context["member_comparison"] = build_member_to_member_comparison(
            viewer_member,
            member,
            selected_department,
            start_date,
            end_date,
            today_only=dashboard_data["selected_scope"] == "today",
        )
    else:
        context["member_comparison"] = None
    return context


def _resolve_comparison_target_member(request: HttpRequest):
    viewer_member = get_member_profile(request.user)
    target_member = viewer_member
    requested_member_id = (request.GET.get("member") or "").strip()
    if requested_member_id:
        target_member = _member_directory_queryset().filter(pk=requested_member_id).first() or viewer_member
    return viewer_member, target_member


def _comparison_scope_bounds(selected_card, *, today):
    scope = selected_card["scope"]
    if scope == "today":
        return today, today
    if scope == "period" and selected_card.get("period_obj"):
        period = selected_card["period_obj"]
        return period.start_date, min(period.end_date, today)
    if scope == "month":
        return selected_card["month_start"], today
    return selected_card.get("custom_start_date"), selected_card.get("custom_end_date")


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect(_login_redirect_url(request.user))

    form = DairyMetricsLoginForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.user)
        return redirect(_login_redirect_url(form.user, fallback=request.POST.get("next", "")))
    return render(request, "dairymetrics/login.html", {"form": form, "next": request.GET.get("next", "")})


def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    return redirect("dairymetrics_login")


@require_dairymetrics_member
def dashboard(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    context = _build_member_dashboard_context(request=request, member=member) if member else {
        "page_title": "DairyMetrics",
        "member": None,
        "departments": [],
        "selected_department": None,
        "selected_card": None,
        "entry_form": None,
        "is_admin": request.user.is_staff,
        "readonly_dashboard": False,
        "viewer_member": None,
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest" and member:
        return JsonResponse(
            {
                "card_html": render_to_string(
                    "dairymetrics/partials/dashboard_card.html",
                    context,
                    request=request,
                ),
                "form_html": render_to_string(
                    "dairymetrics/partials/entry_modal_form.html",
                    context,
                    request=request,
                ),
                "target_form_html": render_to_string(
                    "dairymetrics/partials/scope_target_modal_form.html",
                    context,
                    request=request,
                ),
                "department_code": context["selected_department"].code if context["selected_department"] else "",
            }
        )
    return render(request, "dairymetrics/dashboard.html", context)


@require_dairymetrics_member
def member_index(request: HttpRequest) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    member_rows = _build_member_directory()
    selected_member_id = request.GET.get("member")
    selected_member = None
    if selected_member_id:
        selected_member = next((row["member"] for row in member_rows if str(row["member"].id) == selected_member_id), None)
    if not selected_member and member_rows:
        selected_member = member_rows[0]["member"]
    if not selected_member:
        return render(
            request,
            "dairymetrics/dashboard.html",
            {
                "page_title": "DairyMetrics",
                "member": None,
                "viewer_member": viewer_member,
                "departments": [],
                "selected_department": None,
                "selected_card": None,
                "scope_options": [],
                "selected_scope": "today",
                "entry_form": None,
                "scope_target_form": None,
                "scope_target_form_action": "",
                "is_admin": request.user.is_staff,
                "readonly_dashboard": True,
                "member_rows": [],
                "member_filter_departments": [],
                "member_filter_default_code": "",
            },
        )
    return member_dashboard(request, selected_member.id)


@require_dairymetrics_member
def member_dashboard(request: HttpRequest, member_id: int) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    target_member = get_object_or_404(_member_directory_queryset(), pk=member_id)
    context = _build_member_dashboard_context(
        request=request,
        member=target_member,
        readonly=True,
        viewer_member=viewer_member,
    )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "card_html": render_to_string(
                    "dairymetrics/partials/dashboard_card.html",
                    context,
                    request=request,
                ),
                "form_html": "",
                "target_form_html": "",
                "department_code": context["selected_department"].code if context["selected_department"] else "",
                "page_subtitle": f"{viewer_member.name}さんでログイン中" if viewer_member else "管理者としてメンバーデータを閲覧中",
                "viewed_member_name": target_member.name,
            }
        )
    return render(request, "dairymetrics/dashboard.html", context)


@require_dairymetrics_member
def comparison_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff:
        return redirect("dairymetrics_admin_overview")
    viewer_member, target_member = _resolve_comparison_target_member(request)
    if target_member:
        selected_department_code = (request.GET.get("department") or "").strip()
        selected_scope = (request.GET.get("scope") or "today").strip()
        selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
        selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
        selected_period_id = (request.GET.get("period_id") or "").strip()
        dashboard_data = build_member_dashboard(
            target_member,
            today=timezone.localdate(),
            department_code=selected_department_code,
            scope=selected_scope,
            start_date=selected_start_date,
            end_date=selected_end_date,
            period_id=selected_period_id or None,
        )
        context = {
            "page_title": "DairyMetrics",
            "member": target_member,
            "viewer_member": viewer_member,
            "departments": dashboard_data["departments"],
            "selected_department": dashboard_data["selected_department"],
            "selected_card": dashboard_data["selected_card"],
            "scope_options": dashboard_data["scope_options"],
            "selected_scope": dashboard_data["selected_scope"],
            "is_admin": request.user.is_staff,
            "comparison_member_id": (
                str(target_member.id) if viewer_member and target_member.id != viewer_member.id else ""
            ),
            "return_dashboard_url": (
                reverse("dairymetrics_member_dashboard", args=[target_member.id])
                if viewer_member and target_member.id != viewer_member.id
                else reverse("dairymetrics_dashboard")
            )
        }
        if viewer_member and target_member.id != viewer_member.id and dashboard_data["selected_card"]:
            start_date, end_date = _comparison_scope_bounds(
                dashboard_data["selected_card"],
                today=timezone.localdate(),
            )
            context["member_comparison"] = build_member_to_member_comparison(
                viewer_member,
                target_member,
                dashboard_data["selected_department"],
                start_date,
                end_date,
                today_only=dashboard_data["selected_scope"] == "today",
            )
        else:
            context["member_comparison"] = None
    else:
        context = {
        "page_title": "DairyMetrics",
        "member": None,
        "viewer_member": None,
        "departments": [],
        "selected_department": None,
        "selected_card": None,
        "scope_options": [],
        "selected_scope": "today",
        "entry_form": None,
        "is_admin": request.user.is_staff,
        "comparison_member_id": "",
        "return_dashboard_url": reverse("dairymetrics_dashboard"),
        "member_comparison": None,
    }
    return render(request, "dairymetrics/comparison.html", context)


@require_dairymetrics_member
def member_overview(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    selected_department_code = (request.GET.get("department") or "").strip()
    overview = build_member_daily_overview(
        member,
        department_code=selected_department_code,
        today=timezone.localdate(),
    )
    context = {
        "member": member,
        "is_admin": request.user.is_staff,
        "today": overview["today"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "submission_summary": overview["submission_summary"],
        "today_department_totals": overview["today_department_totals"],
        "activity_cards": overview["activity_cards"],
    }
    return render(request, "dairymetrics/member_overview.html", context)


@require_dairymetrics_member
def member_monthly_overview(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    target_month = parse_date(f"{(request.GET.get('month') or timezone.localdate().strftime('%Y-%m'))}-01")
    if not target_month:
        target_month = timezone.localdate().replace(day=1)
    selected_department_code = (request.GET.get("department") or "").strip()
    active_tab = (request.GET.get("tab") or "field").strip()
    if active_tab not in {"field", "adjustment"}:
        active_tab = "field"

    overview = build_member_month_overview(
        member,
        target_month=target_month,
        department_code=selected_department_code,
        today=timezone.localdate(),
    )
    context = {
        "member": member,
        "is_admin": request.user.is_staff,
        "target_month": target_month,
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "month_days": overview["month_days"],
        "rows": overview["field_rows"] if active_tab == "field" else overview["adjustment_rows"],
        "active_tab": active_tab,
    }
    return render(request, "dairymetrics/member_monthly.html", context)


@require_dairymetrics_member
def comparison_ranking_detail(request: HttpRequest) -> HttpResponse:
    if request.user.is_staff:
        return JsonResponse({"error": "admin_not_supported"}, status=404)
    viewer_member, target_member = _resolve_comparison_target_member(request)
    if not target_member:
        return JsonResponse({"error": "member_not_found"}, status=404)

    metric_key = (request.GET.get("metric") or "").strip()
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
    selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
    selected_period_id = (request.GET.get("period_id") or "").strip()
    detail = build_member_ranking_detail(
        target_member,
        today=timezone.localdate(),
        department_code=selected_department_code,
        scope=selected_scope,
        start_date=selected_start_date,
        end_date=selected_end_date,
        period_id=selected_period_id or None,
        metric_key=metric_key,
    )
    if not detail:
        return JsonResponse({"error": "metric_not_found"}, status=404)

    return JsonResponse(
        {
            "modal_html": render_to_string(
                "dairymetrics/partials/ranking_detail_modal.html",
                detail,
                request=request,
            ),
        }
    )


@require_dairymetrics_admin
def admin_ranking_overview(request: HttpRequest) -> HttpResponse:
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_scope = (request.GET.get("scope") or "today").strip()
    selected_start_date = parse_date((request.GET.get("start_date") or "").strip())
    selected_end_date = parse_date((request.GET.get("end_date") or "").strip())
    overview = build_admin_ranking_overview(
        department_code=selected_department_code,
        scope=selected_scope,
        start_date=selected_start_date,
        end_date=selected_end_date,
        today=timezone.localdate(),
    )
    context = {
        "today": overview["today"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "ranking_metrics": overview["ranking_metrics"],
        "scope_options": overview["scope_options"],
        "selected_scope": overview["selected_scope"],
        "scope_summary": overview["scope_summary"],
        "custom_start_date": overview["custom_start_date"],
        "custom_end_date": overview["custom_end_date"],
    }
    return render(request, "dairymetrics/admin_ranking.html", context)


@require_dairymetrics_member
def scope_target_form(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    scope = (request.GET.get("scope") or "").strip()
    department_code = (request.GET.get("department") or "").strip()
    department = Department.objects.filter(
        is_active=True,
        code=department_code,
        member_links__member=member,
    ).first()
    if scope not in {"period", "month"} or not department:
        return redirect("dairymetrics_dashboard")

    today = timezone.localdate()
    selected_card = build_member_dashboard(
        member,
        today=today,
        department_code=department.code,
        scope=scope,
    )["selected_card"]
    if not selected_card or selected_card["scope"] != scope:
        return redirect("dairymetrics_dashboard")
    form = MemberScopeTargetForm(
        request.POST or None,
        member=member,
        scope=scope,
        department=department,
        period=selected_card.get("period_obj"),
        target_month=selected_card.get("month_start"),
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(f"{reverse('dairymetrics_dashboard')}?department={department.code}&scope={scope}&saved=1")
    return render(
        request,
        "dairymetrics/scope_target_form.html",
        {
            "form": form,
            "scope_target_form": form,
            "scope_target_form_action": f"{reverse('dairymetrics_scope_target')}?department={department.code}&scope={scope}",
            "scope": scope,
            "department": department,
        },
    )


@require_dairymetrics_member
def entry_form(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    initial_date = parse_date((request.GET.get("date") or "").strip()) or timezone.localdate()
    selected_department = (request.GET.get("department") or "").strip()
    form = _build_entry_form(
        member=member,
        data=request.POST or None,
        department_code=selected_department,
        entry_date=initial_date,
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        existing = MemberDailyMetricEntry.objects.filter(
            member=member,
            department=saved.department,
            entry_date=saved.entry_date,
        ).first()
        if existing and saved.pk is None:
            saved.pk = existing.pk
            saved.created_at = existing.created_at
        saved.member = member
        saved.input_source = MemberDailyMetricEntry.SOURCE_MEMBER
        submit_action = (request.POST.get("submit_action") or "save").strip()
        is_closing = submit_action == "close_activity"
        saved.activity_closed = is_closing
        saved.activity_closed_at = timezone.now() if is_closing else None
        saved.save()
        return redirect(f"{reverse('dairymetrics_dashboard')}?saved=1")

    departments = _member_departments(member)
    context = {
        "form": form,
        "member": member,
        "departments": departments,
        "selected_department_code": selected_department,
    }
    return render(request, "dairymetrics/entry_form.html", context)


@require_dairymetrics_member
def entry_form_v2_demo(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    entry_date = parse_date((request.GET.get("date") or "").strip()) or timezone.localdate()
    selected_department = (request.GET.get("department") or "").strip()
    context = _build_entry_v2_demo_context(
        member=member,
        selected_department=selected_department,
        entry_date=entry_date,
    )
    return render(request, "dairymetrics/entry_form_v2_demo.html", context)


@require_dairymetrics_member
def metrics_v2_demo(request: HttpRequest) -> HttpResponse:
    viewer_member = get_member_profile(request.user)
    departments, selected_department = _resolve_metrics_v2_department(request=request, member=viewer_member)
    if not selected_department:
        return redirect("dairymetrics_dashboard")
    selected_member = None
    raw_member_id = (request.GET.get("member") or "").strip()
    if request.user.is_staff and raw_member_id.isdigit():
        selected_member = (
            _member_directory_queryset()
            .filter(pk=int(raw_member_id), department_links__department=selected_department)
            .distinct()
            .first()
        )

    today = timezone.localdate()
    requested_scope = (request.GET.get("scope") or "recent").strip()
    requested_month = _parse_month_input(request.GET.get("month") or "")
    requested_period = None
    raw_period_id = (request.GET.get("period_id") or "").strip()
    if raw_period_id.isdigit():
        requested_period = Period.objects.filter(pk=int(raw_period_id)).first()
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
    available_periods = list(Period.objects.order_by("-end_date", "-start_date", "-id")[:18])

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
    return render(request, "dairymetrics/metrics_v2_demo.html", context)


@require_dairymetrics_member
def entry_form_v2_transaction_demo(request: HttpRequest) -> HttpResponse:
    member = get_member_profile(request.user)
    if not member:
        return redirect("dairymetrics_dashboard")

    raw_department_code = (
        request.POST.get("department_code")
        or request.POST.get("department")
        or request.GET.get("department")
        or ""
    ).strip()
    raw_entry_date = (
        request.POST.get("entry_date")
        or request.POST.get("target_entry_date")
        or request.GET.get("date")
        or ""
    ).strip()
    entry_date = parse_date(raw_entry_date) or timezone.localdate()
    selected_department = raw_department_code

    status_message = ""
    open_entry_panel = False
    open_personal_target_panel = False
    open_department_target_panel = False
    open_closeout_panel = False
    personal_setup_form = None
    department_target_form = None
    transaction_form = None
    closeout_form = None
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        selected_department = raw_department_code
        selected_department_obj = Department.objects.filter(
            is_active=True,
            code=selected_department,
            member_links__member=member,
        ).distinct().first()

        if action == "save_personal_setup":
            personal_setup_form = DairymetricsV2PersonalSetupForm(request.POST, member=member)
            if personal_setup_form.is_valid():
                selected_department_obj = personal_setup_form.cleaned_data["department"]
                selected_department = selected_department_obj.code
                entry_date = personal_setup_form.cleaned_data["entry_date"]
                entry, _ = MemberDailyMetricEntry.objects.get_or_create(
                    member=member,
                    department=selected_department_obj,
                    entry_date=entry_date,
                    defaults={"input_source": MemberDailyMetricEntry.SOURCE_MEMBER},
                )
                entry.daily_target_count = personal_setup_form.cleaned_data["daily_target_count"]
                entry.daily_target_cs_count = personal_setup_form.cleaned_data.get("daily_target_cs_count") or 0
                entry.daily_target_refugee_count = personal_setup_form.cleaned_data.get("daily_target_refugee_count") or 0
                entry.daily_target_amount = personal_setup_form.cleaned_data["daily_target_amount"]
                entry.location_name = personal_setup_form.cleaned_data["location_name"]
                entry.input_source = MemberDailyMetricEntry.SOURCE_MEMBER
                entry.save(
                    update_fields=[
                        "daily_target_count",
                        "daily_target_cs_count",
                        "daily_target_refugee_count",
                        "daily_target_amount",
                        "location_name",
                        "input_source",
                        "updated_at",
                    ]
                )
                get_or_create_department_daily_summary(
                    department=selected_department_obj,
                    entry_date=entry_date,
                    member=member,
                )
                return redirect(
                    build_v2_redirect_url(
                        department_code=selected_department,
                        entry_date=entry_date,
                        saved="personal_setup",
                    )
                )
            selected_department_obj = personal_setup_form.fields["department"].queryset.filter(
                pk=request.POST.get("department")
            ).first()
            if selected_department_obj:
                selected_department = selected_department_obj.code
            status_message = "個人の日目標を確認してください。"
            open_personal_target_panel = True
        elif action == "save_department_target":
            if not selected_department_obj:
                status_message = "部署を選択してください。"
            else:
                department_target_form = DairymetricsV2DepartmentTargetForm(request.POST)
                if department_target_form.is_valid():
                    entry_date = department_target_form.cleaned_data["entry_date"]
                    summary = get_or_create_department_daily_summary(
                        department=selected_department_obj,
                        entry_date=entry_date,
                        member=member,
                    )
                    summary.daily_target_amount = department_target_form.cleaned_data["daily_target_amount"]
                    if summary.created_by_id is None:
                        summary.created_by = member
                    summary.updated_by = member
                    summary.save(update_fields=["daily_target_amount", "created_by", "updated_by", "updated_at"])
                    return redirect(
                        build_v2_redirect_url(
                            department_code=selected_department,
                            entry_date=entry_date,
                            saved="department_target",
                        )
                    )
                status_message = "部署全体の日目標を確認してください。"
                open_department_target_panel = True
        elif action in {"save_transaction", "save_transaction_preview"}:
            if not selected_department_obj:
                status_message = "部署を選択してください。"
            else:
                transaction_id = (request.POST.get("transaction_id") or "").strip()
                transaction_instance = None
                if transaction_id.isdigit():
                    transaction_instance = (
                        MemberMetricTransaction.objects.filter(
                            id=int(transaction_id),
                            entry__member=member,
                            entry__department=selected_department_obj,
                            entry__entry_date=entry_date,
                        )
                        .select_related("entry")
                        .first()
                    )
                transaction_form = DairymetricsV2TransactionForm(
                    request.POST,
                    instance=transaction_instance,
                    department=selected_department_obj,
                )
                if transaction_form.is_valid():
                    entry, _ = MemberDailyMetricEntry.objects.get_or_create(
                        member=member,
                        department=selected_department_obj,
                        entry_date=entry_date,
                        defaults={"input_source": MemberDailyMetricEntry.SOURCE_MEMBER},
                    )
                    transaction_obj = transaction_form.save(commit=False)
                    transaction_obj.entry = entry
                    transaction_obj.save()
                    return redirect(
                        build_v2_redirect_url(
                            department_code=selected_department,
                            entry_date=entry_date,
                            saved="transaction",
                            preview_tx=transaction_obj.id if action == "save_transaction_preview" else None,
                        )
                    )
                status_message = "決済明細を確認してください。"
                open_entry_panel = True
        elif action == "send_transaction_mock":
            preview_tx_id = (request.POST.get("preview_transaction_id") or "").strip()
            preview_history_id = (request.POST.get("preview_history_id") or "").strip()
            edited_subject = (request.POST.get("preview_subject") or "").strip()
            edited_body = (request.POST.get("preview_body") or "").strip()
            if not selected_department_obj:
                status_message = "送信対象の決済を確認してください。"
            else:
                preview_transaction = None
                if preview_tx_id.isdigit():
                    preview_transaction = (
                        MemberMetricTransaction.objects.filter(
                            id=int(preview_tx_id),
                            entry__member=member,
                            entry__department=selected_department_obj,
                            entry__entry_date=entry_date,
                        )
                        .select_related("entry", "entry__department")
                        .first()
                    )
                elif preview_history_id.isdigit():
                    history_obj = (
                        MailSendHistory.objects.filter(
                            id=int(preview_history_id),
                            department=selected_department_obj,
                            activity_date=entry_date,
                            is_test=False,
                        )
                        .select_related("transaction", "transaction__entry", "transaction__entry__department")
                        .first()
                    )
                    if history_obj:
                        preview_transaction = history_obj.transaction
                if not preview_transaction:
                    status_message = "送信対象の決済が見つかりません。"
                else:
                    existing_history = None
                    if preview_history_id.isdigit():
                        existing_history = (
                            MailSendHistory.objects.filter(
                                id=int(preview_history_id),
                                transaction=preview_transaction,
                                is_test=False,
                            )
                            .select_related("transaction")
                            .first()
                        )
                    recipient_group = get_default_mail_group(department=selected_department_obj)
                    preview_context = _build_entry_v2_transaction_demo_context(
                        member=member,
                        selected_department=selected_department,
                        entry_date=entry_date,
                        preview_transaction=preview_transaction,
                    )
                    preview_payload = preview_context["preview_payload"] or build_transaction_mail_preview(
                        member=member,
                        department_code=selected_department,
                        transaction_obj=preview_transaction,
                        progress_cards=preview_context["progress_cards"],
                    )
                    subject = edited_subject or preview_payload["subject"]
                    body = edited_body or preview_payload["body"]
                    try:
                        send_transaction_mail_mock(
                            sender_member=member,
                            transaction=preview_transaction,
                            recipient_group=recipient_group,
                            subject=subject,
                            body=body,
                            existing_history=existing_history,
                        )
                    except Exception as exc:
                        record_transaction_mail_failure(
                            sender_member=member,
                            transaction=preview_transaction,
                            recipient_group=recipient_group,
                            subject=subject,
                            body=body,
                            existing_history=existing_history,
                            error_code=exc.__class__.__name__,
                            error_message=str(exc),
                        )
                        return redirect(
                            build_v2_redirect_url(
                                department_code=selected_department,
                                entry_date=entry_date,
                                saved="mail_failed",
                            )
                        )
                    return redirect(
                        build_v2_redirect_url(
                            department_code=selected_department,
                            entry_date=entry_date,
                            saved="mail_sent",
                        )
                    )
        elif action == "save_closeout":
            if not selected_department_obj:
                status_message = "部署を選択してください。"
            else:
                entry = MemberDailyMetricEntry.objects.filter(
                    member=member,
                    department=selected_department_obj,
                    entry_date=entry_date,
                ).first()
                if not entry:
                    status_message = "先に決済を登録してください。"
                    open_closeout_panel = True
                else:
                    closeout_form = DairymetricsV2CloseoutForm(request.POST, instance=entry)
                    if closeout_form.is_valid():
                        closeout_entry = closeout_form.save(commit=False)
                        closeout_entry.activity_closed = True
                        closeout_entry.activity_closed_at = timezone.now()
                        closeout_entry.input_source = MemberDailyMetricEntry.SOURCE_MEMBER
                        closeout_entry.save(
                            update_fields=[
                                "approach_count",
                                "communication_count",
                                "activity_closed",
                                "activity_closed_at",
                                "input_source",
                                "updated_at",
                            ]
                        )
                        summary = get_or_create_department_daily_summary(
                            department=selected_department_obj,
                            entry_date=entry_date,
                            member=member,
                        )
                        summary.recalculate_from_entries()
                        return redirect(
                            build_v2_redirect_url(
                                department_code=selected_department,
                                entry_date=entry_date,
                                saved="closeout",
                            )
                        )
                    status_message = "最終実績の入力内容を確認してください。"
                    open_closeout_panel = True

    preview_transaction = None
    preview_tx_id = request.GET.get("preview_tx")
    if preview_tx_id and preview_tx_id.isdigit():
        preview_transaction = (
            MemberMetricTransaction.objects.filter(
                id=int(preview_tx_id),
                entry__member=member,
                entry__department__code=selected_department,
                entry__entry_date=entry_date,
            )
            .select_related("entry", "entry__department")
            .first()
        )

    if not status_message:
        saved = (request.GET.get("saved") or "").strip()
        status_message = {
            "personal_setup": "個人の日目標を保存しました。",
            "department_target": "部署全体の日目標を保存しました。",
            "transaction": "決済明細を登録しました。",
            "mail_sent": "メール履歴を保存しました。",
            "mail_failed": "メール送信に失敗しました。復旧後に再送してください。",
            "closeout": "活動終了時の最終実績を保存しました。",
        }.get(saved, "")

    context = _build_entry_v2_transaction_demo_context(
        member=member,
        selected_department=selected_department,
        entry_date=entry_date,
        personal_setup_form=personal_setup_form,
        department_target_form=department_target_form,
        transaction_form=transaction_form,
        closeout_form=closeout_form,
        status_message=status_message,
        open_entry_panel=open_entry_panel,
        open_personal_target_panel=open_personal_target_panel,
        open_department_target_panel=open_department_target_panel,
        open_closeout_panel=open_closeout_panel,
        preview_transaction=preview_transaction,
    )
    return render(request, "dairymetrics/entry_form_v2_transaction_demo.html", context)


@require_dairymetrics_admin
def admin_overview(request: HttpRequest) -> HttpResponse:
    selected_department_code = (request.GET.get("department") or "").strip()
    overview = build_admin_daily_overview(
        department_code=selected_department_code,
        today=timezone.localdate(),
    )
    context = {
        "today": overview["today"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "submission_summary": overview["submission_summary"],
        "today_department_totals": overview["today_department_totals"],
        "activity_cards": overview["activity_cards"],
        "ranking_metrics": overview["ranking_metrics"],
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "overview_html": render_to_string(
                    "dairymetrics/partials/admin_overview_content.html",
                    context,
                    request=request,
                ),
                "department_code": context["selected_department"].code if context["selected_department"] else "",
            }
        )
    return render(request, "dairymetrics/admin_overview.html", context)


@require_dairymetrics_admin
def admin_monthly_overview(request: HttpRequest) -> HttpResponse:
    target_month = parse_date(f"{(request.GET.get('month') or timezone.localdate().strftime('%Y-%m'))}-01")
    if not target_month:
        target_month = timezone.localdate().replace(day=1)
    selected_department_code = (request.GET.get("department") or "").strip()
    selected_sort = (request.GET.get("sort") or "activity_days").strip()
    if selected_sort not in {"activity_days", "amount", "approach", "count"}:
        selected_sort = "activity_days"
    active_tab = (request.GET.get("tab") or "field").strip()
    if active_tab not in {"field", "adjustment"}:
        active_tab = "field"
    overview = build_admin_month_overview(
        target_month=target_month,
        department_code=selected_department_code,
        sort_key=selected_sort,
        today=timezone.localdate(),
    )
    context = {
        "target_month": target_month,
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "month_days": overview["month_days"],
        "rows": overview["field_rows"] if active_tab == "field" else overview["adjustment_rows"],
        "active_tab": active_tab,
        "selected_sort": overview["selected_sort"],
        "sort_options": overview["sort_options"],
        "activity_summary": overview["activity_summary"],
    }
    return render(request, "dairymetrics/admin_monthly.html", context)


@require_dairymetrics_admin
def admin_monthly_update_cell(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    member_id = request.POST.get("member_id")
    department_code = (request.POST.get("department") or "").strip()
    entry_date = parse_date((request.POST.get("entry_date") or "").strip())
    field_name = (request.POST.get("field") or "").strip()
    raw_value = (request.POST.get("value") or "").strip()

    if not member_id or not department_code or not entry_date or not field_name:
        return JsonResponse({"error": "invalid_request"}, status=400)

    department = get_object_or_404(Department.objects.filter(is_active=True), code=department_code)
    member = get_object_or_404(
        Member.objects.filter(department_links__department=department).distinct(),
        pk=member_id,
    )
    payload, status = _apply_admin_monthly_update(
        member=member,
        department=department,
        entry_date=entry_date,
        field_name=field_name,
        raw_value=raw_value,
    )
    return JsonResponse(payload, status=status)


@require_dairymetrics_admin
def admin_monthly_bulk_update(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    changes = payload.get("changes")
    if not isinstance(changes, list):
        return JsonResponse({"error": "invalid_request"}, status=400)
    if not changes:
        return JsonResponse({"ok": True, "updated_count": 0})

    with transaction.atomic():
        for index, change in enumerate(changes):
            member_id = str(change.get("member_id") or "").strip()
            department_code = str(change.get("department") or "").strip()
            entry_date = parse_date(str(change.get("entry_date") or "").strip())
            field_name = str(change.get("field") or "").strip()
            raw_value = str(change.get("value") or "").strip()

            if not member_id or not department_code or not entry_date or not field_name:
                return JsonResponse({"error": "invalid_request", "index": index}, status=400)

            department = get_object_or_404(Department.objects.filter(is_active=True), code=department_code)
            member = get_object_or_404(
                Member.objects.filter(department_links__department=department).distinct(),
                pk=member_id,
            )
            result, status = _apply_admin_monthly_update(
                member=member,
                department=department,
                entry_date=entry_date,
                field_name=field_name,
                raw_value=raw_value,
            )
            if status != 200:
                result["index"] = index
                return JsonResponse(result, status=status)

    return JsonResponse({"ok": True, "updated_count": len(changes)})


@require_dairymetrics_admin
def admin_monthly_comparison(request: HttpRequest) -> HttpResponse:
    target_month = parse_date(f"{(request.GET.get('month') or timezone.localdate().strftime('%Y-%m'))}-01")
    if not target_month:
        target_month = timezone.localdate().replace(day=1)
    compare_month = parse_date((request.GET.get("compare_month") or ""))
    if compare_month:
        compare_month = compare_month.replace(day=1)
    else:
        previous_month_end = target_month.replace(day=1) - timedelta(days=1)
        compare_month = previous_month_end.replace(day=1)
    selected_department_code = (request.GET.get("department") or "").strip()
    overview = build_admin_month_comparison(
        target_month=target_month,
        compare_month=compare_month,
        department_code=selected_department_code,
    )
    context = {
        "target_month": overview["target_month"],
        "compare_month": overview["compare_month"],
        "departments": overview["departments"],
        "selected_department": overview["selected_department"],
        "rows": overview["rows"],
        "monthly_department_totals": overview["monthly_department_totals"],
    }
    return render(request, "dairymetrics/admin_monthly_comparison.html", context)


@require_dairymetrics_admin
def adjustment_create(request: HttpRequest) -> HttpResponse:
    form = MetricAdjustmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        adjustment = form.save(commit=False)
        adjustment.created_by = request.user
        adjustment.save()
        return redirect(f"{reverse('dairymetrics_admin_monthly_overview')}?month={adjustment.target_date.strftime('%Y-%m')}")

    recent_adjustments = MetricAdjustment.objects.select_related("member", "department", "created_by")[:10]
    return render(
        request,
        "dairymetrics/admin_adjustment_form.html",
        {"form": form, "recent_adjustments": recent_adjustments},
    )
