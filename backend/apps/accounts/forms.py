from django import forms


class LoginForm(forms.Form):
    login_id = forms.ChoiceField(
        label="ログイン種別",
        choices=(
            ("admin", "管理者"),
            ("report", "報告"),
        ),
        widget=forms.Select(),
    )
    password = forms.CharField(
        label="パスワード",
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "パスワード"}),
    )
