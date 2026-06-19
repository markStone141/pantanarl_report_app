from django import forms

from apps.accounts.models import Department, Member


class MemberRegistrationForm(forms.Form):
    name = forms.CharField(
        label="名前",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "メンバー名"}),
    )
    un_activity_code = forms.CharField(
        label="UN活動コード",
        required=False,
        max_length=5,
        widget=forms.TextInput(attrs={"placeholder": "5桁の数字", "inputmode": "numeric", "pattern": "[0-9]{5}"}),
    )
    email = forms.EmailField(
        label="メールアドレス",
        required=False,
        widget=forms.EmailInput(attrs={"placeholder": "獲得メール送信用アドレス"}),
    )
    departments = forms.ModelMultipleChoiceField(
        label="所属部署",
        required=False,
        queryset=Department.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )
    default_department = forms.ModelChoiceField(
        label="メイン部署",
        required=False,
        queryset=Department.objects.none(),
        empty_label="未設定",
    )
    auth_login_id = forms.CharField(
        label="ログインID",
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "ナレッジ共有アプリ用ID"}),
    )
    auth_password = forms.CharField(
        label="ログインパスワード",
        required=False,
        max_length=128,
        widget=forms.PasswordInput(
            attrs={"placeholder": "新規設定時は必須（編集時は変更時のみ入力）"},
            render_value=False,
        ),
    )

    def clean_un_activity_code(self):
        code = (self.cleaned_data.get("un_activity_code") or "").strip()
        if not code:
            return None
        if len(code) != 5 or not code.isdigit():
            raise forms.ValidationError("UN活動コードは5桁の数字で入力してください。")
        return code


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
    show_in_dashboard_submission = forms.BooleanField(
        label="提出状況一覧に表示",
        required=False,
        initial=True,
    )
    show_in_dashboard_progress = forms.BooleanField(
        label="目標進捗に表示",
        required=False,
        initial=True,
    )


class TargetMetricForm(forms.Form):
    label = forms.CharField(
        label="項目名",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "例: 件数"}),
    )
    code = forms.CharField(
        label="項目コード",
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
