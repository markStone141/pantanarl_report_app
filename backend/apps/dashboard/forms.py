from django import forms


class MemberRegistrationForm(forms.Form):
    name = forms.CharField(
        label="名前",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "メンバー名"}),
    )
    login_id = forms.CharField(
        label="ログインID",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "例: un_ishii"}),
    )
    password = forms.CharField(
        label="パスワード",
        max_length=128,
        widget=forms.PasswordInput(attrs={"placeholder": "パスワード"}),
    )
