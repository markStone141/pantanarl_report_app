from apps.performance.services.trends import entry_final_amount_value, entry_final_count_value


def count_text(entry, adjustment_totals):
    if entry.department.code == "WV":
        total_cs = int(entry.cs_count or 0) + int(adjustment_totals["cs_count"])
        total_refugee = int(entry.refugee_count or 0) + int(adjustment_totals["refugee_count"])
        return f"{total_cs + total_refugee}件"
    total_count = entry_final_count_value(entry=entry, adjustment_totals=adjustment_totals)
    return f"{total_count}件"


def wv_count_detail_text(*, cs_count: int, refugee_count: int) -> str:
    return f"(CS {int(cs_count or 0)}件 / 難民 {int(refugee_count or 0)}件)"


def amount_text(entry, adjustment_totals):
    total_amount = entry_final_amount_value(entry=entry, adjustment_totals=adjustment_totals)
    return f"{total_amount:,}円"


def field_count_text(entry):
    if entry.department.code == "WV":
        return f"CS {int(entry.cs_count or 0)} / 難民 {int(entry.refugee_count or 0)}"
    return f"{int(entry.result_count or 0)}件"


def field_amount_text(entry):
    return f"{int(entry.support_amount or 0):,}円"


def final_count_text(*, department_code, totals):
    if department_code == "WV":
        total_cs = int(totals.get("cs_count") or 0)
        total_refugee = int(totals.get("refugee_count") or 0)
        return f"{total_cs + total_refugee}件"
    total_count = final_count_value(department_code=department_code, totals=totals)
    return f"{total_count}件"


def final_count_subtext(*, department_code, totals):
    if department_code != "WV":
        return ""
    return wv_count_detail_text(
        cs_count=int(totals.get("cs_count") or 0),
        refugee_count=int(totals.get("refugee_count") or 0),
    )


def final_count_value(*, department_code, totals):
    if department_code == "WV":
        return int(totals.get("cs_count") or 0) + int(totals.get("refugee_count") or 0)
    return (
        int(totals.get("result_count") or 0)
        + int(totals.get("return_postal_count") or 0)
        + int(totals.get("return_qr_count") or 0)
    )


def final_amount_text(*, totals):
    total_amount = (
        int(totals.get("support_amount") or 0)
        + int(totals.get("return_postal_amount") or 0)
        + int(totals.get("return_qr_amount") or 0)
    )
    return f"{total_amount:,}円"
