from django.urls import path

from .views import dashboard_index, member_delete, member_settings

urlpatterns = [
    path("", dashboard_index, name="dashboard_index"),
    path("members/", member_settings, name="member_settings"),
    path("members/<int:member_id>/delete/", member_delete, name="member_delete"),
]
