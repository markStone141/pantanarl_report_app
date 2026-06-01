from datetime import date

from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Department
from apps.common.target_periods import current_active_period
from apps.mail.models import MailRecipientGroup, MailSendHistory

from apps.dairymetrics.forms import (
    DairymetricsV2CloseoutForm,
    DairymetricsV2DepartmentTargetForm,
    DairymetricsV2PersonalSetupForm,
    DairymetricsV2TransactionForm,
    MemberDailyMetricEntryForm,
)
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction
from apps.dairymetrics.services.entry_v2 import (
    build_transaction_mail_preview,
    build_v2_department_activity_rows,
    entry_count_breakdown_text,
    entry_total_count,
    get_default_mail_group,
    get_month_target_amount,
    get_period_target_amount,
    get_previous_department_target_amount,
    get_previous_personal_targets,
    is_wv_department,
    transaction_result_type_label,
)


def build_entry_form(*, member, data=None, department_code="", entry_date=None):
    entry_date = entry_date or timezone.localdate()
    instance = None
    if department_code:
        instance = (
            MemberDailyMetricEntry.objects.filter(
                member=member,
                department__code=department_code,
                entry_date=entry_date,
            )
            .select_related("department")
            .first()
        )
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


def member_departments(member):
    return Department.objects.filter(is_active=True, member_links__member=member).distinct().order_by("code")


def resolve_metrics_v2_department(*, request, member):
    requested_code = (request.GET.get("department") or "").strip()
    if request.user.is_staff:
        departments = list(Department.objects.filter(is_active=True).order_by("code"))
    else:
        departments = list(member_departments(member))
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


def parse_month_input(raw_value: str) -> date | None:
    from django.utils.dateparse import parse_date

    raw_value = (raw_value or "").strip()
    if len(raw_value) != 7:
        return None
    return parse_date(f"{raw_value}-01")


def _existing_entry_department_code_for_date(*, member, departments, entry_date):
    department_ids = [department.id for department in departments]
    if not department_ids:
        return ""
    existing_entry = (
        MemberDailyMetricEntry.objects.filter(
            member=member,
            department_id__in=department_ids,
            entry_date=entry_date,
        )
        .select_related("department")
        .order_by("-updated_at", "-id")
        .first()
    )
    if existing_entry and existing_entry.department:
        return existing_entry.department.code
    existing_summary = (
        DepartmentDailyMetricSummary.objects.filter(
            department_id__in=department_ids,
            entry_date=entry_date,
        )
        .select_related("department")
        .order_by("-updated_at", "-id")
        .first()
    )
    if existing_summary and existing_summary.department:
        return existing_summary.department.code
    return ""


def default_entry_department_code(*, member, departments, selected_department, entry_date=None):
    if selected_department:
        return selected_department
    if entry_date is not None:
        existing_entry_department_code = _existing_entry_department_code_for_date(
            member=member,
            departments=departments,
            entry_date=entry_date,
        )
        if existing_entry_department_code:
            return existing_entry_department_code
    department_codes = [department.code for department in departments]
    if member.default_department and member.default_department.code in department_codes:
        return member.default_department.code
    return department_codes[0] if department_codes else ""


def build_entry_v2_demo_context(*, member, selected_department, entry_date, age_bands, gender_bands, nationality_bands):
    departments = list(member_departments(member))
    selected_department_code = default_entry_department_code(
        member=member,
        departments=departments,
        selected_department=selected_department,
        entry_date=entry_date,
    )
    selected_department_obj = next(
        (department for department in departments if department.code == selected_department_code),
        None,
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
        "selected_department_id": selected_department_obj.id if selected_department_obj else "",
        "entry_date": entry_date,
        "initial_total_count": initial_count,
        "initial_total_amount": initial_amount,
        "age_bands": age_bands,
        "gender_bands": gender_bands,
        "nationality_bands": nationality_bands,
        "is_admin": False,
        "demo_mode": True,
    }


def build_demo_progress_card(*, label, current_amount, target_amount, helper_text="", target_source=""):
    current_amount = int(current_amount or 0)
    target_amount = int(target_amount or 0)
    signed_gap_amount = target_amount - current_amount if target_amount else 0
    remaining_amount = max(target_amount - current_amount, 0) if target_amount else 0
    achievement_rate = round((current_amount / target_amount) * 100, 1) if target_amount else None
    return {
        "label": label,
        "current_amount": current_amount,
        "target_amount": target_amount,
        "remaining_amount": remaining_amount,
        "signed_gap_amount": signed_gap_amount,
        "achievement_rate": achievement_rate,
        "helper_text": helper_text,
        "target_source": target_source,
        "has_target": bool(target_amount),
        "is_complete": bool(target_amount) and current_amount >= target_amount,
    }


def first_non_empty_line(text):
    if not text:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def build_entry_v2_transaction_demo_context(
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
    age_bands,
    gender_bands,
    nationality_bands,
    target_count_options,
    target_amount_options,
    transaction_amount_options,
    wv_refugee_amount_options,
):
    base_context = build_entry_v2_demo_context(
        member=member,
        selected_department=selected_department,
        entry_date=entry_date,
        age_bands=age_bands,
        gender_bands=gender_bands,
        nationality_bands=nationality_bands,
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
    personal_total_amount = int(getattr(existing_entry, "support_amount", 0) or 0)
    current_location_name = getattr(existing_entry, "location_name", "") or ""
    department_day_total = int(getattr(department_summary, "support_amount", 0) or 0)
    department_day_target = int(getattr(department_summary, "daily_target_amount", 0) or 0)

    active_period = current_active_period(target_date=entry_date)
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
        build_demo_progress_card(
            label="個人の日目標",
            current_amount=personal_total_amount,
            target_amount=personal_target_amount,
            helper_text=f"{member.name}さんの当日累計",
            target_source="本人の日目標" if personal_target_amount or personal_target_count else "",
        ),
        build_demo_progress_card(
            label="全体の日目標",
            current_amount=department_day_total,
            target_amount=department_day_target,
            helper_text=f"{selected_department_code or '-'} の当日累計",
            target_source="部署全体の日目標" if department_day_target else "",
        ),
        build_demo_progress_card(
            label="路程目標",
            current_amount=period_total_amount,
            target_amount=period_target_amount,
            helper_text=period_label,
            target_source=period_target_source,
        ),
        build_demo_progress_card(
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
    transaction_form_is_wv = is_wv_department(selected_department_obj)
    transaction_wv_result_type_choices = (
        list(transaction_form.fields["wv_result_type"].choices)
        if transaction_form_is_wv and "wv_result_type" in transaction_form.fields
        else []
    )
    transaction_wv_result_type_value = (
        transaction_form["wv_result_type"].value()
        if transaction_form_is_wv and "wv_result_type" in transaction_form.fields
        else ""
    ) or MemberMetricTransaction.WV_RESULT_CS
    transaction_wv_cs_count_value = str(
        (
            transaction_form["wv_cs_count"].value()
            if transaction_form_is_wv and "wv_cs_count" in transaction_form.fields
            else 1
        )
        or 1
    )
    transaction_wv_refugee_amount_value = str(
        (
            transaction_form["wv_refugee_amount"].value()
            if transaction_form_is_wv and "wv_refugee_amount" in transaction_form.fields
            else 0
        )
        or 0
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
        "selected_department_id": selected_department_obj.id if selected_department_obj else "",
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
        "target_count_options": target_count_options,
        "target_amount_options": target_amount_options,
        "transaction_amount_options": transaction_amount_options,
        "wv_refugee_amount_options": wv_refugee_amount_options,
        "personal_target_count_value": personal_target_count_value,
        "personal_target_cs_count_value": personal_target_cs_count_value,
        "personal_target_refugee_count_value": personal_target_refugee_count_value,
        "personal_target_amount_value": personal_target_amount_value,
        "personal_location_name_value": personal_location_name_value,
        "department_target_amount_value": department_target_amount_value,
        "transaction_amount_value": transaction_amount_value,
        "transaction_form_is_wv": transaction_form_is_wv,
        "transaction_wv_result_type_choices": transaction_wv_result_type_choices,
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
