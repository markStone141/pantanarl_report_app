from django.urls import path

from .views import (
    dashboard_index,
    department_delete,
    department_settings,
    member_delete,
    member_settings,
)

urlpatterns = [
    path("", dashboard_index, name="dashboard_index"),
    path("members/", member_settings, name="member_settings"),
    path("members/<int:member_id>/delete/", member_delete, name="member_delete"),
    path("departments/", department_settings, name="department_settings"),
    path(
        "departments/<int:department_id>/delete/",
        department_delete,
        name="department_delete",
    ),
]
