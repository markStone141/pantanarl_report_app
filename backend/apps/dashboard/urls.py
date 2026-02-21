from django.urls import path

from .views import dashboard_index

urlpatterns = [
    path("", dashboard_index, name="dashboard_index"),
]
