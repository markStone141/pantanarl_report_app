from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from apps.mail.models import MailDepartmentRouting, MailRecipientGroup, MailSendHistory
from apps.common.report_metrics import _metric_kind
from apps.targets.models import (
    DepartmentMonthTarget,
    DepartmentPeriodTarget,
    MonthTargetMetricValue,
    PeriodTargetMetricValue,
)

from ..models import DepartmentDailyMetricSummary, MemberDailyMetricEntry


def build_v2_redirect_url(*, department_code, entry_date, saved="", preview_tx=None):
    query = {
        "department": department_code,
        "date": entry_date.strftime("%Y-%m-%d"),
    }
    if saved:
        query["saved"] = saved
    if preview_tx:
        query["preview_tx"] = str(preview_tx)
    return f"{reverse('dairymetrics_entry_v2_transaction_demo')}?{urlencode(query)}"


def get_previous_personal_targets(*, member, department, entry_date):
    previous_entry = (
        MemberDailyMetricEntry.objects.filter(
            member=member,
            department=department,
            entry_date=entry_date - timedelta(days=1),
        )
        .only(
            "daily_target_count",
            "daily_target_amount",
            "daily_target_cs_count",
            "daily_target_refugee_count",
        )
        .first()
    )
    if not previous_entry:
        return 1, 3000, 0, 1
    return (
        int(previous_entry.daily_target_count or 1),
        int(previous_entry.daily_target_amount or 3000),
        int(previous_entry.daily_target_cs_count or 0),
        int(previous_entry.daily_target_refugee_count or 0),
    )


def get_previous_department_target_amount(*, department, entry_date):
    previous_summary = (
        DepartmentDailyMetricSummary.objects.filter(
            department=department,
            entry_date=entry_date - timedelta(days=1),
        )
        .only("daily_target_amount")
        .first()
    )
    if not previous_summary:
        return 10000
    return int(previous_summary.daily_target_amount or 10000)


def get_or_create_department_daily_summary(*, department, entry_date, member):
    summary, created = DepartmentDailyMetricSummary.objects.get_or_create(
        department=department,
        entry_date=entry_date,
        defaults={
            "created_by": member,
            "updated_by": member,
        },
    )
    if not created and summary.updated_by_id is None:
        summary.updated_by = member
        summary.save(update_fields=["updated_by", "updated_at"])
    return summary


def is_wv_department(department_or_code) -> bool:
    if not department_or_code:
        return False
    if hasattr(department_or_code, "code"):
        return department_or_code.code == "WV"
    return department_or_code == "WV"


def entry_total_count(entry) -> int:
    if not entry:
        return 0
    if is_wv_department(entry.department):
        total_count = int(entry.cs_count or 0) + int(entry.refugee_count or 0)
        return total_count or int(entry.result_count or 0)
    return int(entry.result_count or 0)


def entry_count_breakdown_text(entry) -> str:
    if not entry:
        return "0件"
    if is_wv_department(entry.department):
        cs_count = int(entry.cs_count or 0)
        refugee_count = int(entry.refugee_count or 0)
        total_count = cs_count + refugee_count
        if total_count == 0 and int(entry.result_count or 0) > 0:
            total_count = int(entry.result_count or 0)
        return f"CS {cs_count} / 難民 {refugee_count} / 合計 {total_count}"
    return f"{int(entry.result_count or 0)}件"


def transaction_result_type_label(transaction_obj) -> str:
    if not transaction_obj or not is_wv_department(transaction_obj.entry.department):
        return "会員"
    if transaction_obj.wv_result_type == transaction_obj.WV_RESULT_REFUGEE:
        return "難民"
    if transaction_obj.wv_result_type == transaction_obj.WV_RESULT_CS:
        return "CS"
    if transaction_obj.wv_result_type == transaction_obj.WV_RESULT_BOTH:
        return "CS+難民"
    return "未分類"


def transaction_mail_status(transaction_obj):
    latest_history = transaction_obj.mail_send_histories.order_by("-last_attempt_at", "-sent_at", "-created_at", "-id").first()
    if latest_history and latest_history.status == MailSendHistory.STATUS_FAILED:
        return "送信失敗"
    if latest_history and latest_history.status == MailSendHistory.STATUS_SENT:
        if latest_history.sent_at and transaction_obj.updated_at and transaction_obj.updated_at > latest_history.sent_at:
            return "修正済み未送信"
        if latest_history.is_resend:
            return "修正再送済み"
        return "送信済み"
    return "未送信"


def find_duplicate_transaction(*, entry, cleaned_data, exclude_id=None):
    transactions = entry.transactions.all()
    if exclude_id:
        transactions = transactions.exclude(id=exclude_id)

    target_support_amount = int(cleaned_data.get("support_amount") or 0)
    target_age_band = cleaned_data.get("age_band") or ""
    target_is_student = bool(cleaned_data.get("is_student"))
    target_gender = cleaned_data.get("gender") or ""
    target_nationality = cleaned_data.get("nationality_type") or ""
    target_location = (cleaned_data.get("location") or "").strip()
    target_comment = (cleaned_data.get("comment") or "").strip()
    target_result_type = cleaned_data.get("wv_result_type") or ""
    target_cs_count = int(cleaned_data.get("wv_cs_count") or 0)
    target_refugee_amount = int(cleaned_data.get("wv_refugee_amount") or 0)

    for transaction in transactions.order_by("-created_at", "-id"):
        if int(transaction.support_amount or 0) != target_support_amount:
            continue
        if (transaction.age_band or "") != target_age_band:
            continue
        if bool(transaction.is_student) != target_is_student:
            continue
        if (transaction.gender or "") != target_gender:
            continue
        if (transaction.nationality_type or "") != target_nationality:
            continue
        if (transaction.location or "").strip() != target_location:
            continue
        if (transaction.comment or "").strip() != target_comment:
            continue
        if entry.department.code == "WV":
            if (transaction.wv_result_type or "") != target_result_type:
                continue
            if int(transaction.wv_cs_count or 0) != target_cs_count:
                continue
            if int(transaction.wv_refugee_amount or 0) != target_refugee_amount:
                continue
        return transaction
    return None


def build_v2_department_activity_rows(*, department, entry_date):
    if not department:
        return {"active": [], "closed": []}

    rows = []
    entries = (
        MemberDailyMetricEntry.objects.filter(
            department=department,
            entry_date=entry_date,
            input_source=MemberDailyMetricEntry.SOURCE_MEMBER,
        )
        .select_related("member", "department")
        .order_by("-updated_at", "member__name")
    )
    for today_entry in entries:
        count_value = entry_total_count(today_entry)
        rows.append(
            {
                "member_name": today_entry.member.name,
                "member_id": today_entry.member_id,
                "status_label": "活動終了" if today_entry.activity_closed else "活動中",
                "is_closed": bool(today_entry.activity_closed),
                "updated_at": timezone.localtime(today_entry.updated_at),
                "updated_label": timezone.localtime(today_entry.updated_at).strftime("%H:%M"),
                "department_name": department.name,
                "count_value": count_value,
                "count_label": entry_count_breakdown_text(today_entry),
                "amount_value": int(today_entry.support_amount or 0),
                "target_amount_value": int(today_entry.daily_target_amount or 0),
                "location_name": today_entry.location_name or "",
            }
        )
    return {
        "active": [row for row in rows if not row["is_closed"]],
        "closed": [row for row in rows if row["is_closed"]],
    }


def get_default_mail_group(*, department):
    if not department:
        return None
    routing = (
        MailDepartmentRouting.objects.filter(department=department)
        .select_related("recipient_group")
        .first()
    )
    if routing and routing.recipient_group.is_active:
        return routing.recipient_group
    group = (
        MailRecipientGroup.objects.filter(
            is_active=True,
            related_departments=department,
        )
        .order_by("name", "id")
        .first()
    )
    if group:
        return group
    group = (
        MailRecipientGroup.objects.filter(
            is_active=True,
            department=department,
        )
        .order_by("name", "id")
        .first()
    )
    if group:
        return group
    return (
        MailRecipientGroup.objects.filter(
            is_active=True,
            department__isnull=True,
        )
        .order_by("name", "id")
        .first()
    )


def _amount_metric_value(queryset):
    for metric_value in queryset.select_related("metric").order_by("metric__display_order", "id"):
        if _metric_kind(metric_code=metric_value.metric.code, unit=metric_value.metric.unit or "") == "amount":
            return int(metric_value.value or 0), True
    return None


def get_period_target_amount(*, period, department):
    resolved = _amount_metric_value(
        PeriodTargetMetricValue.objects.filter(
            period=period,
            department=department,
            metric__is_active=True,
        )
    )
    if resolved is not None:
        return resolved
    legacy_target = DepartmentPeriodTarget.objects.filter(
        period=period,
        department=department,
    ).first()
    return int(getattr(legacy_target, "target_amount", 0) or 0), bool(legacy_target)


def get_month_target_amount(*, target_month, department):
    resolved = _amount_metric_value(
        MonthTargetMetricValue.objects.filter(
            target_month=target_month,
            department=department,
            metric__is_active=True,
        )
    )
    if resolved is not None:
        return resolved
    legacy_target = DepartmentMonthTarget.objects.filter(
        department=department,
        target_month=target_month,
    ).first()
    return int(getattr(legacy_target, "target_amount", 0) or 0), bool(legacy_target)


def build_transaction_mail_preview(*, member, department_code, transaction_obj, progress_cards):
    personal_card, department_card, period_card, month_card = progress_cards
    result_type_label = transaction_result_type_label(transaction_obj)
    subject = (
        f"{transaction_obj.entry.entry_date.month}/{transaction_obj.entry.entry_date.day}"
        f"{member.name}です({department_code or 'UN①'})"
    )
    if is_wv_department(transaction_obj.entry.department):
        cs_count = int(transaction_obj.wv_cs_count or 0)
        refugee_amount = int(transaction_obj.wv_refugee_amount or 0)
        parts = []
        if cs_count:
            parts.append(f"CS{cs_count}口 {cs_count * transaction_obj.WV_CS_UNIT_AMOUNT:,}円")
        if refugee_amount:
            parts.append(f"難民1件 {refugee_amount:,}円")
        result_line = " / ".join(parts) or f"{result_type_label} {transaction_obj.support_amount:,}円"
    else:
        result_line = f"会員1名 {transaction_obj.support_amount:,}円"
    def format_gap(card):
        gap_amount = int(card.get("signed_gap_amount") or 0)
        if gap_amount < 0:
            return f"+{abs(gap_amount):,}円"
        return f"{gap_amount:,}円"

    body = "\n".join(
        [
            department_code or "",
            result_line,
            f"日目まで {format_gap(department_card)}",
            f"路目まで {format_gap(period_card)}",
            f"月目まで {format_gap(month_card)}",
            "",
            " ".join(
                filter(
                    None,
                    [
                        transaction_obj.get_age_band_display(),
                        "学生" if transaction_obj.is_student else "",
                        transaction_obj.get_gender_display(),
                        transaction_obj.get_nationality_type_display(),
                    ],
                )
            ),
            transaction_obj.location,
            transaction_obj.comment,
            "",
            "栄光在天✨全体精誠に感謝です！",
            "",
            f"{personal_card['current_amount']:,}/{personal_card['target_amount']:,}円",
        ]
    ).strip()
    return {
        "subject": subject,
        "body": body,
    }
