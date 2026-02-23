from django import forms


class LoginForm(forms.Form):
    login_id = forms.CharField(
        label="ログインID",
        max_length=64,
        widget=forms.TextInput(
            attrs={"placeholder": "un_report / un_ishii / admin"}
        ),
    )
    password = forms.CharField(
        label="パスワード",
        required=False,
        widget=forms.PasswordInput(
            attrs={"placeholder": "共通パスワード（デモ）"}
        ),
    )
