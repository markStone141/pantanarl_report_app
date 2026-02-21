from django.urls import path

from .views import target_index

urlpatterns = [
    path("", target_index, name="target_index"),
]
