from django import forms

from apps.accounts.models import Member


class TalksLoginForm(forms.Form):
    login_id = forms.CharField(label="ID", max_length=64)
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "IDまたはパスワードが違います。",
    }

    member = None

    def clean(self):
        cleaned_data = super().clean()
        login_id = (cleaned_data.get("login_id") or "").strip()
        password = cleaned_data.get("password") or ""
        if not login_id or not password:
            return cleaned_data

        member = Member.objects.active().filter(login_id=login_id).first()
        if not member or member.password != password:
            raise forms.ValidationError(self.error_messages["invalid_login"])

        self.member = member
        return cleaned_data
