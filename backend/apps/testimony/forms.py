import os

from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.models import Member

from .models import Article

User = get_user_model()
REPORT_USERNAME = os.getenv("REPORT_LOGIN_USERNAME", "report")
ADMIN_USERNAME = os.getenv("ADMIN_LOGIN_USERNAME", "admin")


class TestimonyLoginForm(forms.Form):
    login_id = forms.CharField(label="ID", max_length=64)
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "IDまたはパスワードが正しくありません。",
    }

    member = None
    user = None

    def clean(self):
        cleaned_data = super().clean()
        login_id = (cleaned_data.get("login_id") or "").strip()
        password = cleaned_data.get("password") or ""
        if not login_id or not password:
            return cleaned_data

        user = User.objects.filter(username=login_id).first()
        member = Member.objects.active().filter(user=user).first() if user else None
        is_ops_user = bool(user and user.username in {ADMIN_USERNAME, REPORT_USERNAME})
        is_admin_user = bool(user and (user.is_staff or user.is_superuser))
        if not user or not user.check_password(password):
            raise forms.ValidationError(self.error_messages["invalid_login"])
        if not member and not is_ops_user and not is_admin_user:
            raise forms.ValidationError(self.error_messages["invalid_login"])

        self.user = user
        self.member = member
        return cleaned_data


class ArticleForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = ["title", "body", "author", "video_url", "product", "testimonied_at"]
