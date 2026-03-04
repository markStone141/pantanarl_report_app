from django.urls import path

from .views import talks_detail, talks_index

urlpatterns = [
    path("", talks_index, name="talks_index"),
    path("<int:thread_id>/", talks_detail, name="talks_detail"),
]
