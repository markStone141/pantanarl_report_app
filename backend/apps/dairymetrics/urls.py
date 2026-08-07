from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="dairymetrics_login"),
    path("logout/", views.logout_view, name="dairymetrics_logout"),
    path("entry-v2-transaction/personal-setup-fields/", views.entry_v2_personal_setup_fields, name="dairymetrics_entry_v2_personal_setup_fields"),
    path("entry-v2-transaction/reaction/", views.transaction_reaction_update, name="dairymetrics_transaction_reaction_update"),
    path("entry-v2-transaction/", views.entry_form_v2_transaction_demo, name="dairymetrics_entry_v2_transaction_demo"),
    path("metrics-v2/", views.metrics_v2_demo, name="dairymetrics_metrics_v2_demo"),
    path("metrics-report/", views.metrics_report, name="dairymetrics_metrics_report"),
    path("metrics-report/export/", views.metrics_report_export, name="dairymetrics_metrics_report_export"),
]
