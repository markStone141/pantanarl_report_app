from django.urls import reverse
from django.utils import timezone

from apps.dairymetrics.models import MemberMetricTransaction
from apps.mail.models import MailSendHistory


def build_department_today_transaction_rows(*, department, target_date):
    transactions = (
        MemberMetricTransaction.objects.filter(
            entry__department=department,
            entry__entry_date=target_date,
        )
        .select_related("entry", "entry__member", "entry__department")
        .order_by("-entry__updated_at", "-id")
    )
    rows = []
    for transaction in transactions:
        if department.code == "WV":
            if transaction.wv_result_type == MemberMetricTransaction.WV_RESULT_CS:
                type_text = f"CS {int(transaction.wv_cs_count or 0)}口"
            elif transaction.wv_result_type == MemberMetricTransaction.WV_RESULT_REFUGEE:
                type_text = f"難民 {int(transaction.wv_refugee_amount or 0):,}円"
            else:
                type_text = (
                    f"CS {int(transaction.wv_cs_count or 0)}口 + "
                    f"難民 {int(transaction.wv_refugee_amount or 0):,}円"
                )
        else:
            type_text = "1件"
        rows.append(
            {
                "id": transaction.id,
                "member_name": transaction.entry.member.name,
                "location_name": transaction.location or transaction.entry.location_name or "-",
                "amount_text": f"{int(transaction.support_amount or 0):,}円",
                "type_text": type_text,
                "detail_text": (
                    f"{transaction.get_age_band_display()} / "
                    f"{transaction.get_gender_display()} / "
                    f"{transaction.get_nationality_type_display()}"
                ),
                "comment": transaction.comment,
                "edit_url": reverse("performance_transaction_edit", args=[transaction.id]),
                "delete_url": reverse("performance_transaction_delete", args=[transaction.id]),
            }
        )
    return rows


def build_department_today_mail_rows(*, department, target_date):
    histories = (
        MailSendHistory.objects.filter(
            department=department,
            activity_date=target_date,
            is_test=False,
            transaction__isnull=False,
        )
        .select_related(
            "sender_member",
            "transaction",
            "transaction__entry",
            "transaction__entry__member",
            "recipient_group",
        )
        .order_by("-created_at", "-id")
    )
    return [
        {
            "member_name": (
                history.transaction.entry.member.name
                if history.transaction and history.transaction.entry_id
                else "-"
            ),
            "subject": history.subject_snapshot,
            "status_text": history.get_status_display(),
            "status_value": history.status,
            "sent_at_text": (
                timezone.localtime(history.sent_at).strftime("%Y/%m/%d %H:%M")
                if history.sent_at
                else "-"
            ),
            "recipient_text": history.sent_to_snapshot or "-",
            "body_text": history.body_snapshot,
            "error_text": history.error_message,
        }
        for history in histories
    ]


def build_department_today_detail_context(*, department, target_date, next_url=""):
    return {
        "today_detail_date": target_date,
        "today_detail_next_url": next_url,
        "today_transaction_rows": build_department_today_transaction_rows(
            department=department,
            target_date=target_date,
        ),
        "today_mail_rows": build_department_today_mail_rows(
            department=department,
            target_date=target_date,
        ),
    }
