from django.urls import path

from .views import (
    target_index,
    target_month_history_detail,
    target_month_settings,
    target_period_history_detail,
    target_period_settings,
)

urlpatterns = [
    path("", target_index, name="target_index"),
    path("history/month-detail/", target_month_history_detail, name="target_month_history_detail"),
    path("history/period-detail/<int:period_id>/", target_period_history_detail, name="target_period_history_detail"),
    path("month/", target_month_settings, name="target_month_settings"),
    path("period/", target_period_settings, name="target_period_settings"),
]
