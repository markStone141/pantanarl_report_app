from django import forms
from django.contrib.auth import authenticate

from apps.accounts.models import Department, Member

from .models import MemberDailyMetricEntry, MetricAdjustment


class DairyMetricsLoginForm(forms.Form):
    login_id = forms.CharField(label="ID", max_length=150)
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "IDまたはパスワードが正しくありません。",
        "not_allowed": "DairyMetrics を利用できるメンバーではありません。",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user = None

    def clean(self):
        cleaned_data = super().clean()
        login_id = cleaned_data.get("login_id")
        password = cleaned_data.get("password")
        if not login_id or not password:
            return cleaned_data

        user = authenticate(self.request, username=login_id, password=password)
        if not user:
            raise forms.ValidationError(self.error_messages["invalid_login"])
        if not user.is_staff and not Member.objects.filter(user=user, is_active=True).exists():
            raise forms.ValidationError(self.error_messages["not_allowed"])
        self.user = user
        return cleaned_data


class MemberDailyMetricEntryForm(forms.ModelForm):
    class Meta:
        model = MemberDailyMetricEntry
        fields = [
            "department",
            "entry_date",
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "cs_count",
            "refugee_count",
            "location_name",
            "memo",
        ]
        widgets = {
            "entry_date": forms.DateInput(attrs={"type": "date"}),
            "memo": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, member=None, **kwargs):
        super().__init__(*args, **kwargs)
        departments = Department.objects.filter(is_active=True)
        if member is not None:
            departments = departments.filter(member_links__member=member).distinct()
        self.fields["department"].queryset = departments.order_by("code")
        for name in [
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "cs_count",
            "refugee_count",
        ]:
            self.fields[name].min_value = 0


class MetricAdjustmentForm(forms.ModelForm):
    class Meta:
        model = MetricAdjustment
        fields = [
            "member",
            "department",
            "target_date",
            "source_type",
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "cs_count",
            "refugee_count",
            "note",
        ]
        widgets = {
            "target_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = Member.objects.active().filter(department_links__department__is_active=True).distinct()
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")
        for name in [
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "cs_count",
            "refugee_count",
        ]:
            self.fields[name].min_value = 0
