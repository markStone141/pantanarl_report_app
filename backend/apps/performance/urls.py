from django.urls import path

from .views import (
    performance_adjustment_delete,
    performance_adjustments,
    performance_entry_edit,
    performance_index,
    performance_member_detail,
)

urlpatterns = [
    path("", performance_index, name="performance_index"),
    path("entries/<int:entry_id>/", performance_entry_edit, name="performance_entry_edit"),
    path("members/<int:member_id>/<int:department_id>/", performance_member_detail, name="performance_member_detail"),
    path("adjustments/", performance_adjustments, name="performance_adjustments"),
    path("adjustments/<int:adjustment_id>/delete/", performance_adjustment_delete, name="performance_adjustment_delete"),
]
