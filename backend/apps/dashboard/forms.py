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
        label="所属部署",
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
        label="部署コード",
        max_length=32,
        widget=forms.TextInput(attrs={"placeholder": "例: UN / WV / STYLE1"}),
    )
    default_reporter = forms.ModelChoiceField(
        label="デフォルト報告者",
        required=False,
        queryset=Member.objects.none(),
        empty_label="未設定",
    )


class TargetMetricForm(forms.Form):
    label = forms.CharField(
        label="指標名",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "例: 件数"}),
    )
    code = forms.CharField(
        label="指標コード",
        max_length=32,
        widget=forms.TextInput(attrs={"placeholder": "例: count"}),
    )
    unit = forms.CharField(
        label="単位",
        required=False,
        max_length=16,
        widget=forms.TextInput(attrs={"placeholder": "例: 件 / 円"}),
    )
    display_order = forms.IntegerField(
        label="表示順",
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"min": "1"}),
    )
    is_active = forms.BooleanField(
        label="有効",
        required=False,
        initial=True,
    )
