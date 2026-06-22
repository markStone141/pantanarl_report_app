import os

from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.models import Member

from .models import Article, Product

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
        fields = ["title", "product", "author", "testimonied_at", "body", "video_url"]
        labels = {
            "title": "タイトル",
            "author": "証者・投稿者名",
            "testimonied_at": "証日",
            "body": "本文",
            "video_url": "動画URL",
            "product": "商材",
        }
        widgets = {
            "testimonied_at": forms.DateInput(
                attrs={
                    "placeholder": "2026/06/22",
                    "inputmode": "numeric",
                },
                format="%Y/%m/%d",
            ),
            "body": forms.Textarea(attrs={"rows": 10}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["testimonied_at"].input_formats = ["%Y/%m/%d", "%Y-%m-%d"]
        self.fields["testimonied_at"].help_text = "年/月/日 の形式で入力してください。例: 2026/06/22"


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "description"]
        labels = {
            "name": "商材名",
            "description": "説明",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }
