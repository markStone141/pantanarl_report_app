from django.urls import path

from .views import monthly_guide_index


urlpatterns = [
    path("", monthly_guide_index, name="monthly_guide_index"),
]

