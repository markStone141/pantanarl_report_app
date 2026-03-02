from django import forms


class LoginForm(forms.Form):
    login_id = forms.ChoiceField(
        label="ログイン種別",
        choices=(
            ("report", "報告"),
            ("admin", "管理者"),
        ),
        initial="report",
        widget=forms.Select(),
    )
    password = forms.CharField(
        label="パスワード",
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "パスワード"}),
    )
