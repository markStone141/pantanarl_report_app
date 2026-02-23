from django.urls import path

from .views import (
    report_history,
    report_index,
    report_style1,
    report_style2,
    report_un,
    report_wv,
)

urlpatterns = [
    path("", report_index, name="report_index"),
    path("history/", report_history, name="report_history"),
    path("un/", report_un, name="report_un"),
    path("wv/", report_wv, name="report_wv"),
    path("style1/", report_style1, name="report_style1"),
    path("style2/", report_style2, name="report_style2"),
]
