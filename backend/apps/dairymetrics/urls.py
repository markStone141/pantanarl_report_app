from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="dairymetrics_login"),
    path("logout/", views.logout_view, name="dairymetrics_logout"),
    path("", views.dashboard, name="dairymetrics_dashboard"),
    path("members/", views.member_index, name="dairymetrics_member_index"),
    path("members/<int:member_id>/", views.member_dashboard, name="dairymetrics_member_dashboard"),
    path("compare/", views.comparison_view, name="dairymetrics_compare"),
    path("monthly/", views.member_monthly_overview, name="dairymetrics_member_monthly_overview"),
    path("compare/ranking-detail/", views.comparison_ranking_detail, name="dairymetrics_compare_ranking_detail"),
    path("entry/", views.entry_form, name="dairymetrics_entry"),
    path("targets/scope/", views.scope_target_form, name="dairymetrics_scope_target"),
    path("admin/", views.admin_overview, name="dairymetrics_admin_overview"),
    path("admin/monthly/", views.admin_monthly_overview, name="dairymetrics_admin_monthly_overview"),
    path("admin/monthly/update-cell/", views.admin_monthly_update_cell, name="dairymetrics_admin_monthly_update_cell"),
    path("admin/monthly-comparison/", views.admin_monthly_comparison, name="dairymetrics_admin_monthly_comparison"),
    path("admin/adjustments/new/", views.adjustment_create, name="dairymetrics_adjustment_create"),
]
