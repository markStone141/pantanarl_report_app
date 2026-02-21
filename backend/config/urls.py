from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("reports/", include("apps.reports.urls")),
    path("targets/", include("apps.targets.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("talks/", include("apps.talks.urls")),
]
