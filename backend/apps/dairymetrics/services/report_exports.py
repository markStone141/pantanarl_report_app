from __future__ import annotations

from apps.mail.models import MailSendHistory


def _mail_rows(*, department, scope) -> list[dict]:
    histories = (
        MailSendHistory.objects.filter(
            department=department,
            activity_date__range=(scope.start_date, scope.end_date),
            is_test=False,
        )
        .select_related(
            "sender_member",
            "recipient_group",
            "transaction",
            "transaction__entry",
            "transaction__entry__member",
        )
        .order_by("activity_date", "created_at", "id")
    )
    rows = []
    for history in histories:
        transaction = history.transaction
        entry = transaction.entry if transaction and transaction.entry_id else None
        rows.append(
            {
                "activity_date": history.activity_date.isoformat(),
                "status": history.status,
                "status_label": history.get_status_display(),
                "is_resend": history.is_resend,
                "subject": history.subject_snapshot,
                "body": history.body_snapshot,
                "recipients": history.sent_to_snapshot,
                "sender_member": history.sender_member.name if history.sender_member else "",
                "recipient_group": history.recipient_group.name if history.recipient_group else "",
                "member": entry.member.name if entry else "",
                "transaction_amount": int(transaction.support_amount or 0) if transaction else None,
                "sent_at": history.sent_at.isoformat() if history.sent_at else None,
                "error_code": history.error_code,
                "error_message": history.error_message,
            }
        )
    return rows


def build_report_export_payload(*, department, scope, report) -> dict:
    return {
        "report": {
            "department_code": department.code,
            "department_name": department.name,
            "scope": scope.scope,
            "scope_label": scope.label,
            "period_name": scope.period.name if scope.period else None,
            "start_date": scope.start_date.isoformat(),
            "end_date": scope.end_date.isoformat(),
        },
        "summary": report["summary_cards"],
        "targets": report["target_cards"],
        "adjustment_summary": report["adjustment_cards"],
        "daily_results": report["daily_rows"],
        "adjustment_details": report["adjustment_rows"],
        "member_results": report["member_rows"],
        "attribute_analysis": [
            {
                "title": card["title"],
                "total": card["total_text"],
                "rows": card["rows"],
                "average_amounts": [
                    {"label": label, "amount": amount}
                    for label, amount in zip(card["labels"], card["avg_amounts"])
                ],
            }
            for card in report["distribution_cards"]
        ],
        "emails": _mail_rows(department=department, scope=scope),
    }


def build_report_ai_text(payload: dict) -> str:
    metadata = payload["report"]
    lines = [
        "以下は活動実績の振り返りデータです。",
        "数値の傾向、良かった点、課題、メンバーごとの差、日別の変化、メール内容から読み取れる事項を分析してください。",
        "事実と推測を分け、根拠となる数値やメールを示してください。",
        "",
        "## 集計条件",
        f"部署: {metadata['department_name']} ({metadata['department_code']})",
        f"集計単位: {metadata['scope_label']}",
        f"対象期間: {metadata['start_date']} - {metadata['end_date']}",
    ]
    if metadata["period_name"]:
        lines.append(f"対象路程: {metadata['period_name']}")

    def append_cards(title, cards):
        lines.extend(["", f"## {title}"])
        for card in cards:
            helper = f" ({card['helper']})" if card.get("helper") else ""
            lines.append(f"- {card['label']}: {card['value']}{helper}")

    append_cards("全体集計", payload["summary"])
    append_cards("目標進捗", payload["targets"])
    append_cards("補正実績集計", payload["adjustment_summary"])

    lines.extend(["", "## 日別実績"])
    for row in payload["daily_results"]:
        count_text = (
            f"CS {row['cs_count_text']} / 難民 {row['refugee_count_text']}"
            if metadata["department_code"] == "WV"
            else row["count_text"]
        )
        lines.append(
            f"- {row['date_text']}: {count_text}, 金額 {row['amount_text']}, "
            f"AP {row['approach_text']}, CM {row['communication_text']}"
        )
        for transaction in row["transactions"]:
            lines.append(
                "  - 決済: "
                f"{transaction['member_name']} / {transaction['amount_text']} / {transaction['type_text']} / "
                f"{transaction['age_text']} / {transaction['gender_text']} / {transaction['nationality_text']} / "
                f"現場 {transaction['location_text']} / コメント {transaction['comment'] or '-'}"
            )

    lines.extend(["", "## メンバー別集計"])
    for row in payload["member_results"]:
        count_text = (
            f"CS {row['cs_count_text']} / 難民 {row['refugee_count_text']}"
            if metadata["department_code"] == "WV"
            else row["count_text"]
        )
        lines.append(
            f"- {row['member_name']}: {count_text}, 金額 {row['amount_text']}, "
            f"AP {row['approach_text']}, CM {row['communication_text']}, "
            f"コミュ率 {row['communication_rate_text']}, 決済率 {row['conversion_rate_text']}, "
            f"平均/決済 {row['average_amount_per_decision_text']}, "
            f"平均/稼働 {row['average_amount_per_active_day_text']}, 稼働日数 {row['active_days_text']}"
        )

    lines.extend(["", "## 補正実績明細"])
    for row in payload["adjustment_details"]:
        lines.append(
            f"- {row['date_text']} / {row['member_name']} / {row['type_text']} / "
            f"{row['amount_text']} / 現場 {row['location_text']}"
        )

    lines.extend(["", "## 属性別分析"])
    for card in payload["attribute_analysis"]:
        lines.append(f"### {card['title']} ({card['total']})")
        average_map = {row["label"]: row["amount"] for row in card["average_amounts"]}
        for row in card["rows"]:
            average = average_map.get(row["label"])
            average_text = f", 平均金額 {average:,.1f}円" if average is not None else ""
            lines.append(
                f"- {row['label']}: {row['count_text']} / {row['percent_text']}{average_text}"
            )

    lines.extend(["", "## 送信メール"])
    if not payload["emails"]:
        lines.append("- 対象期間内のメールはありません。")
    for index, mail in enumerate(payload["emails"], start=1):
        lines.extend(
            [
                f"### メール {index}",
                f"- 活動日: {mail['activity_date']}",
                f"- 状態: {mail['status_label']}",
                f"- 再送: {'はい' if mail['is_resend'] else 'いいえ'}",
                f"- メンバー: {mail['member'] or mail['sender_member'] or '-'}",
                f"- 宛先グループ: {mail['recipient_group'] or '-'}",
                f"- 宛先: {mail['recipients'] or '-'}",
                f"- 件名: {mail['subject']}",
                "- 本文:",
                mail["body"] or "-",
            ]
        )
        if mail["error_message"]:
            lines.append(f"- エラー: {mail['error_code']} {mail['error_message']}".strip())

    return "\n".join(lines) + "\n"
