from django.urls import path

from .views import (
    mosaic_dashboard,
    mosaic_interaction_create,
    mosaic_interaction_list,
    mosaic_login,
    mosaic_logout,
    mosaic_master_create,
    mosaic_master_edit,
    mosaic_master_index,
)

urlpatterns = [
    path("login/", mosaic_login, name="mosaic_login"),
    path("logout/", mosaic_logout, name="mosaic_logout"),
    path("", mosaic_dashboard, name="mosaic_dashboard"),
    path("interactions/new/", mosaic_interaction_create, name="mosaic_interaction_create"),
    path("interactions/", mosaic_interaction_list, name="mosaic_interaction_list"),
    path("masters/", mosaic_master_index, name="mosaic_master_index"),
    path("masters/<str:master_type>/new/", mosaic_master_create, name="mosaic_master_create"),
    path("masters/<str:master_type>/<int:pk>/edit/", mosaic_master_edit, name="mosaic_master_edit"),
]
