import json

from django.db import transaction
from django.utils import timezone

from apps.dairymetrics.forms import DairymetricsV2TransactionForm
from apps.dairymetrics.models import DepartmentDailyMetricSummary, MemberDailyMetricEntry, MemberMetricTransaction


def parse_transactions_payload(raw_payload):
    if not raw_payload:
        return []
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        raise ValueError("決済明細のデータ形式が不正です。")
    if not isinstance(payload, list):
        raise ValueError("決済明細のデータ形式が不正です。")
    return payload


def normalize_transaction_payloads(*, department, payload_rows):
    cleaned_transactions = []
    errors = []
    for index, row in enumerate(payload_rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"{index}件目の決済データ形式が不正です。")
            continue
        form = DairymetricsV2TransactionForm(row, department=department)
        if not form.is_valid():
            message = " / ".join(
                f"{field}: {' '.join(error_list)}"
                for field, error_list in form.errors.items()
            )
            errors.append(f"{index}件目: {message}")
            continue
        cleaned_transactions.append(form.cleaned_data)
    return cleaned_transactions, errors


def transaction_preview_rows(*, department, payload_rows):
    previews = []
    for row in payload_rows:
        result_type = row.get("wv_result_type") or ""
        cs_count = int(row.get("wv_cs_count") or 0)
        refugee_amount = int(row.get("wv_refugee_amount") or 0)
        support_amount = int(row.get("support_amount") or 0)
        if department.code == "WV":
            if result_type == MemberMetricTransaction.WV_RESULT_CS:
                amount_text = f"CS {cs_count or 1}口 / {support_amount:,}円"
            elif result_type == MemberMetricTransaction.WV_RESULT_REFUGEE:
                amount_text = f"難民 / {refugee_amount:,}円"
            else:
                amount_text = f"CS {cs_count or 1}口 + 難民 {refugee_amount:,}円 / {support_amount:,}円"
        else:
            amount_text = f"{support_amount:,}円"
        previews.append(
            {
                "amount_text": amount_text,
                "age_band": row.get("age_band", ""),
                "gender": row.get("gender", ""),
                "nationality_type": row.get("nationality_type", ""),
                "comment": row.get("comment", ""),
            }
        )
    return previews


def create_past_entry_with_transactions(
    *,
    member,
    department,
    entry_date,
    location_name,
    approach_count,
    communication_count,
    transactions,
):
    if MemberDailyMetricEntry.objects.filter(member=member, department=department, entry_date=entry_date).exists():
        raise ValueError("その日の実績はすでに登録されています。既存データを修正してください。")

    with transaction.atomic():
        entry = MemberDailyMetricEntry.objects.create(
            member=member,
            department=department,
            entry_date=entry_date,
            location_name=location_name or "",
            approach_count=int(approach_count or 0),
            communication_count=int(communication_count or 0),
            activity_closed=True,
            activity_closed_at=timezone.now(),
            input_source=MemberDailyMetricEntry.SOURCE_ADMIN,
        )
        for cleaned_data in transactions:
            transaction_obj = MemberMetricTransaction(entry=entry)
            for field_name in (
                "support_amount",
                "wv_result_type",
                "wv_cs_count",
                "wv_refugee_amount",
                "age_band",
                "is_student",
                "gender",
                "nationality_type",
                "comment",
            ):
                setattr(transaction_obj, field_name, cleaned_data.get(field_name))
            transaction_obj.location = location_name or ""
            transaction_obj.save()
        summary = DepartmentDailyMetricSummary.get_or_create_for_entry(entry=entry)
        summary.recalculate_from_entries()
        return entry
