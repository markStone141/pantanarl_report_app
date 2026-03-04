from django.urls import path

from .views import talks_detail, talks_index, talks_login, talks_logout

urlpatterns = [
    path("login/", talks_login, name="talks_login"),
    path("logout/", talks_logout, name="talks_logout"),
    path("", talks_index, name="talks_index"),
    path("<int:thread_id>/", talks_detail, name="talks_detail"),
]
