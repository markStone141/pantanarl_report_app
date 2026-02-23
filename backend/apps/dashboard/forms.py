from django import forms

from apps.accounts.models import Department, Member


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
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "パスワード"}),
    )
    departments = forms.ModelMultipleChoiceField(
        label="所属部門",
        required=False,
        queryset=Department.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )


class DepartmentForm(forms.Form):
    name = forms.CharField(
        label="表示名",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "例: UN"}),
    )
    code = forms.CharField(
        label="部門コード",
        max_length=32,
        widget=forms.TextInput(attrs={"placeholder": "例: UN / WV / STYLE1"}),
    )
    default_reporter = forms.ModelChoiceField(
        label="デフォルト責任者",
        required=False,
        queryset=Member.objects.none(),
        empty_label="未設定",
    )
