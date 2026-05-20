from django import forms

from apps.accounts.models import Department, Member

from .models import MailIntegrationSetting, MailRecipientGroup


class MailIntegrationSettingForm(forms.ModelForm):
    client_id = forms.CharField(
        label="Client ID",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "再設定する場合のみ入力"}),
    )
    client_secret = forms.CharField(
        label="Client Secret",
        required=False,
        widget=forms.PasswordInput(
            attrs={"placeholder": "再設定する場合のみ入力"},
            render_value=False,
        ),
    )
    refresh_token = forms.CharField(
        label="Refresh Token",
        required=False,
        widget=forms.PasswordInput(
            attrs={"placeholder": "再設定する場合のみ入力"},
            render_value=False,
        ),
    )

    class Meta:
        model = MailIntegrationSetting
        fields = [
            "sender_email",
            "sender_name",
            "token_uri",
            "is_active",
            "client_id",
            "client_secret",
            "refresh_token",
        ]
        widgets = {
            "sender_email": forms.EmailInput(attrs={"placeholder": "送信元メールアドレス"}),
            "sender_name": forms.TextInput(attrs={"placeholder": "送信元表示名"}),
            "token_uri": forms.URLInput(attrs={"placeholder": "https://oauth2.googleapis.com/token"}),
        }
        labels = {
            "sender_email": "送信元メールアドレス",
            "sender_name": "送信元表示名",
            "token_uri": "Token URI",
            "is_active": "この設定を有効にする",
        }


class MailIntegrationTestForm(forms.Form):
    TARGET_MEMBER = "member"
    TARGET_GROUP = "group"
    TARGET_CHOICES = [
        (TARGET_MEMBER, "メンバー1人へ送る"),
        (TARGET_GROUP, "メールグループへ送る"),
    ]

    target_type = forms.ChoiceField(
        label="テスト送信先",
        choices=TARGET_CHOICES,
        initial=TARGET_MEMBER,
    )
    member = forms.ModelChoiceField(
        label="対象メンバー",
        required=False,
        queryset=Member.objects.none(),
        empty_label="メンバーを選択",
    )
    group = forms.ModelChoiceField(
        label="対象メールグループ",
        required=False,
        queryset=MailRecipientGroup.objects.none(),
        empty_label="メールグループを選択",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = Member.objects.active().exclude(email="").order_by("name")
        self.fields["group"].queryset = MailRecipientGroup.objects.filter(is_active=True).order_by("name")

    def clean(self):
        cleaned_data = super().clean()
        target_type = cleaned_data.get("target_type")
        if target_type == self.TARGET_MEMBER and not cleaned_data.get("member"):
            self.add_error("member", "対象メンバーを選択してください。")
        if target_type == self.TARGET_GROUP and not cleaned_data.get("group"):
            self.add_error("group", "対象メールグループを選択してください。")
        return cleaned_data


class MailRecipientGroupForm(forms.Form):
    name = forms.CharField(
        label="グループ名",
        max_length=128,
        widget=forms.TextInput(attrs={"placeholder": "例: 当日共有グループA"}),
    )
    departments = forms.ModelMultipleChoiceField(
        label="関連部署",
        required=False,
        queryset=Department.objects.filter(is_active=True).order_by("code"),
        widget=forms.CheckboxSelectMultiple,
    )
    members = forms.ModelMultipleChoiceField(
        label="対象メンバー",
        required=False,
        queryset=Member.objects.active().exclude(email="").order_by("name"),
        widget=forms.CheckboxSelectMultiple,
    )
    is_active = forms.BooleanField(
        label="有効",
        required=False,
        initial=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected_departments = []
        source_data = self.data if self.is_bound else self.initial
        if source_data:
            raw_departments = source_data.get("departments", [])
            if hasattr(source_data, "getlist"):
                raw_departments = source_data.getlist("departments")
            if not isinstance(raw_departments, list):
                raw_departments = [raw_departments]
            selected_departments = [
                int(value)
                for value in raw_departments
                if str(value).isdigit()
            ]
        member_queryset = Member.objects.active().exclude(email="")
        if selected_departments:
            member_queryset = member_queryset.filter(
                department_links__department_id__in=selected_departments
            ).distinct()
        self.fields["members"].queryset = member_queryset.order_by("name")
