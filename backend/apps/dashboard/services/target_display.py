import re

from apps.common.report_metrics import _metric_kind, metric_actual_value


def format_adjustment_breakdown(*, code: str, totals: dict) -> str:
    count = int(totals.get("count") or 0)
    amount = int(totals.get("amount") or 0)
    cs_count = int(totals.get("cs_count") or 0)
    refugee_count = int(totals.get("refugee_count") or 0)
    if not any([count, amount, cs_count, refugee_count]):
        return ""
    if code == "WV":
        return f"補正 CS{cs_count}件 / 難民{refugee_count}件 / 金額{amount:,}円"
    return f"補正 件数{count}件 / 金額{amount:,}円"


def append_adjustment_note(*, base_text: str, code: str, totals: dict) -> str:
    note = format_adjustment_breakdown(code=code, totals=totals)
    if not note:
        return base_text
    return f"{base_text}（{note}込み）"


def format_wv_actual_summary(*, totals: dict) -> str:
    cs_count = int(totals.get("cs_count") or 0)
    refugee_count = int(totals.get("refugee_count") or 0)
    amount = int(totals.get("amount") or 0)
    return f"CS {cs_count}件 / 難民 {refugee_count}件 / 金額 {amount:,}円"


def _format_metric_number(*, metric_code: str, value: int, unit: str, use_amount_commas: bool) -> str:
    if _metric_kind(metric_code=metric_code, unit=unit) == "amount" and use_amount_commas:
        return f"{value:,}"
    return str(value)


def build_target_metric_text(*, metrics, target_values: dict) -> str:
    if not metrics:
        return "-"
    parts = []
    for metric in metrics:
        target = int(target_values.get(metric.id, 0) or 0)
        unit = metric.unit or ""
        parts.append(
            f"{metric.label} "
            f"{_format_metric_number(metric_code=metric.code, value=target, unit=unit, use_amount_commas=False)}{unit}"
        )
    return " / ".join(parts)


def build_actual_metric_text(*, metrics, actual_totals: dict, use_amount_commas: bool) -> str:
    if not metrics:
        return "-"
    parts = []
    for metric in metrics:
        unit = metric.unit or ""
        actual = metric_actual_value(
            metric_code=metric.code,
            total_count=actual_totals["count"],
            total_amount=actual_totals["amount"],
            total_cs_count=actual_totals.get("cs_count", 0),
            total_refugee_count=actual_totals.get("refugee_count", 0),
            unit=unit,
        )
        parts.append(
            f"{metric.label} "
            f"{_format_metric_number(metric_code=metric.code, value=actual, unit=unit, use_amount_commas=use_amount_commas)}{unit}"
        )
    return " / ".join(parts)


def build_target_actual_text(
    *,
    code: str,
    metrics,
    target_values: dict,
    actual_totals: dict,
    adjustment_totals: dict,
) -> str:
    if code == "WV":
        return append_adjustment_note(
            base_text=format_wv_actual_summary(totals=actual_totals),
            code=code,
            totals=adjustment_totals,
        )
    actual_text = build_actual_metric_text(
        metrics=metrics,
        actual_totals=actual_totals,
        use_amount_commas=bool(int(adjustment_totals.get("amount") or 0)),
    )
    return append_adjustment_note(
        base_text=actual_text,
        code=code,
        totals=adjustment_totals,
    )


def build_mail_metric_lines(
    *,
    code: str,
    detail_rows: list[dict],
    actual_totals: dict,
    adjustment_totals: dict,
) -> list[str]:
    lines = []
    if code == "WV":
        lines.append(format_wv_actual_summary(totals=actual_totals))
    lines.extend(
        f"{row['label']} {row['actual_text']}/{row['target_text']}{row['unit']} 達成率{row['rate']}"
        for row in detail_rows
    )
    adjustment_note = format_adjustment_breakdown(code=code, totals=adjustment_totals)
    if adjustment_note:
        lines.append(adjustment_note)
    return lines


def mail_period_heading(period_name: str) -> str:
    match = re.search(r"第\d+次路程", period_name or "")
    return match.group(0) if match else (period_name or "-")
