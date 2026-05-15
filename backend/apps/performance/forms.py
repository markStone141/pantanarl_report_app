from django import forms
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.dairymetrics.forms import MemberDailyMetricEntryForm, MetricAdjustmentForm


class PerformanceEntryFilterForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label="部署",
        empty_label="すべての部署",
    )
    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        required=False,
        label="メンバー",
        empty_label="すべてのメンバー",
    )
    date_from = forms.DateField(
        required=False,
        label="開始日",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        label="終了日",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")
        self.fields["member"].queryset = Member.objects.active().order_by("name")
        if not self.is_bound:
            today = timezone.localdate()
            self.initial.setdefault("date_to", today)
            self.initial.setdefault("date_from", today.replace(day=1))


class PerformanceMemberDailyMetricEntryForm(MemberDailyMetricEntryForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, member=None, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")
        if self.instance and self.instance.pk and self.instance.has_transactions:
            for field_name in ("result_count", "support_amount"):
                if field_name in self.fields:
                    self.fields[field_name].disabled = True
                    self.fields[field_name].help_text = "決済明細から自動計算されます。"


class PerformanceMetricAdjustmentForm(MetricAdjustmentForm):
    pass

