from django import forms


class LoginForm(forms.Form):
    login_id = forms.CharField(
        label="ID",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "admin または report"}),
    )
    password = forms.CharField(
        label="パスワード",
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "パスワード"}),
    )
