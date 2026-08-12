from django.contrib import admin
from django.urls import include, path

handler403 = "config.error_views.permission_denied"
handler404 = "config.error_views.page_not_found"
handler500 = "config.error_views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("reports/", include("apps.reports.urls")),
    path("targets/", include("apps.targets.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("talks/", include("apps.talks.urls")),
    path("testimony/", include("apps.testimony.urls")),
    path("metrics/", include("apps.dairymetrics.urls")),
    path("monthly_guide/", include("apps.monthly_guide.urls")),
    path("mail/", include("apps.mail.urls")),
    path("performance/", include("apps.performance.urls")),
    path("mosaic/", include("apps.mosaic.urls")),
]
