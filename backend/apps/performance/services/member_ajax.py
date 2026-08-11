from datetime import timedelta

from django.urls import reverse
from django.utils import timezone


def build_member_dashboard_detail_context(
    *,
    member,
    department,
    entry_rows,
    adjustment_rows,
    is_admin=False,
    readonly_member_view=False,
    selected_date=None,
    reset_url="",
):
    if selected_date is not None:
        detail_heading = f"{selected_date:%Y/%m/%d} の実績"
        detail_description = "グラフで選択した1日分の日次実績です。"
        adjustment_heading = f"{selected_date:%Y/%m/%d} の補正実績"
    else:
        recent_start = timezone.localdate() - timedelta(days=29)
        recent_end = timezone.localdate()
        detail_heading = "直近30日の実績"
        detail_description = (
            f"{recent_start:%Y/%m/%d} - {recent_end:%Y/%m/%d} の日次実績です。"
            "それ以前は実績閲覧で確認します。"
        )
        adjustment_heading = "直近30日の補正実績"

    if readonly_member_view:
        history_url = reverse("performance_member_history_insight", args=[member.id, department.id])
    elif is_admin:
        history_url = reverse("performance_member_history_detail", args=[member.id, department.id])
    else:
        history_url = reverse("performance_member_history")

    return {
        "member": member,
        "department": department,
        "recent_entry_rows": entry_rows,
        "recent_adjustment_rows": adjustment_rows,
        "detail_heading": detail_heading,
        "detail_description": detail_description,
        "detail_adjustment_heading": adjustment_heading,
        "detail_reset_url": reset_url,
        "detail_history_url": history_url,
        "show_reset_detail": selected_date is not None,
        "is_admin_view": is_admin,
        "readonly_member_view": readonly_member_view,
    }
