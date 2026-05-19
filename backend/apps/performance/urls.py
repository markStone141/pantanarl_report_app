from django.urls import path

from .views import (
    performance_adjustment_delete,
    performance_adjustments,
    performance_entry_edit,
    performance_history,
    performance_index,
    performance_login,
    performance_member_dashboard,
    performance_member_detail,
    performance_member_history,
    performance_member_history_detail,
)

urlpatterns = [
    path("login/", performance_login, name="performance_login"),
    path("", performance_index, name="performance_index"),
    path("history/", performance_history, name="performance_history"),
    path("member/", performance_member_dashboard, name="performance_member_dashboard"),
    path("member/history/", performance_member_history, name="performance_member_history"),
    path("entries/<int:entry_id>/", performance_entry_edit, name="performance_entry_edit"),
    path("members/<int:member_id>/<int:department_id>/", performance_member_detail, name="performance_member_detail"),
    path("members/<int:member_id>/<int:department_id>/history/", performance_member_history_detail, name="performance_member_history_detail"),
    path("adjustments/", performance_adjustments, name="performance_adjustments"),
    path("adjustments/<int:adjustment_id>/delete/", performance_adjustment_delete, name="performance_adjustment_delete"),
]
