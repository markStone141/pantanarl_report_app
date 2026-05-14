from django.urls import path

from .views import mail_group_settings, mail_history, mail_integration_settings

urlpatterns = [
    path("settings/", mail_integration_settings, name="mail_integration_settings"),
    path("groups/", mail_group_settings, name="mail_group_settings"),
    path("history/", mail_history, name="mail_history"),
]
