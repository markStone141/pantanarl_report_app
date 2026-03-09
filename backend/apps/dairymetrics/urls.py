from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="dairymetrics_login"),
    path("logout/", views.logout_view, name="dairymetrics_logout"),
    path("", views.dashboard, name="dairymetrics_dashboard"),
    path("compare/", views.comparison_view, name="dairymetrics_compare"),
    path("entry/", views.entry_form, name="dairymetrics_entry"),
    path("admin/", views.admin_overview, name="dairymetrics_admin_overview"),
    path("admin/adjustments/new/", views.adjustment_create, name="dairymetrics_adjustment_create"),
]
