from django.urls import path

from .views import talks_index

urlpatterns = [
    path("", talks_index, name="talks_index"),
]
