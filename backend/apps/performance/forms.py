from django import forms
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.dairymetrics.forms import MemberDailyMetricEntryForm
from apps.dairymetrics.models import MetricAdjustment


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


class PerformanceMetricAdjustmentForm(forms.ModelForm):
    SOURCE_CHOICES = [
        (MetricAdjustment.SOURCE_POSTAL, "郵送"),
        (MetricAdjustment.SOURCE_QR, "QR"),
        (MetricAdjustment.SOURCE_INCREASE, "増額"),
    ]

    amount = forms.IntegerField(label="金額", min_value=0, initial=0)

    class Meta:
        model = MetricAdjustment
        fields = [
            "department",
            "member",
            "target_date",
            "source_type",
        ]
        widgets = {
            "target_date": forms.DateInput(attrs={"type": "date", "class": "dairymetrics-native-date dairymetrics-date-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")
        self.fields["source_type"] = forms.ChoiceField(label="種別", choices=self.SOURCE_CHOICES)
        selected_department = self._resolve_department()
        member_queryset = Member.objects.active().filter(department_links__department__is_active=True).distinct()
        if selected_department is not None:
            member_queryset = member_queryset.filter(department_links__department=selected_department).distinct()
        else:
            member_queryset = member_queryset.none()
        self.fields["member"].queryset = member_queryset.order_by("name")
        self.fields["member"].empty_label = "メンバーを選択"
        self.fields["department"].empty_label = "部署を選択"
        self.fields["target_date"].label = "対象日"
        self.fields["target_date"].initial = self.initial.get("target_date") or timezone.localdate()
        self.order_fields(["department", "member", "target_date", "source_type", "amount"])
        if self.instance and self.instance.pk:
            self.fields["amount"].initial = self._resolve_instance_amount(self.instance)
            if self.instance.source_type in {choice[0] for choice in self.SOURCE_CHOICES}:
                self.fields["source_type"].initial = self.instance.source_type
            else:
                self.fields["source_type"].initial = MetricAdjustment.SOURCE_INCREASE

    def _resolve_department(self):
        if self.is_bound:
            department_id = self.data.get(self.add_prefix("department")) or self.data.get("department")
            if department_id:
                return Department.objects.filter(pk=department_id, is_active=True).first()
        initial_department = self.initial.get("department")
        if isinstance(initial_department, Department):
            return initial_department
        if self.instance and self.instance.pk:
            return self.instance.department
        return None

    @staticmethod
    def _resolve_instance_amount(instance):
        if instance.source_type == MetricAdjustment.SOURCE_POSTAL:
            return int(instance.return_postal_amount or 0)
        if instance.source_type == MetricAdjustment.SOURCE_QR:
            return int(instance.return_qr_amount or 0)
        return int(instance.support_amount or 0)

    def save(self, commit=True):
        adjustment = super().save(commit=False)
        amount = int(self.cleaned_data.get("amount") or 0)
        source_type = self.cleaned_data["source_type"]
        adjustment.source_type = source_type
        adjustment.approach_count = 0
        adjustment.communication_count = 0
        adjustment.result_count = 0
        adjustment.support_amount = 0
        adjustment.return_postal_count = 0
        adjustment.return_postal_amount = 0
        adjustment.return_qr_count = 0
        adjustment.return_qr_amount = 0
        adjustment.cs_count = 0
        adjustment.refugee_count = 0
        adjustment.note = ""
        if source_type == MetricAdjustment.SOURCE_POSTAL:
            adjustment.return_postal_count = 1 if amount > 0 else 0
            adjustment.return_postal_amount = amount
        elif source_type == MetricAdjustment.SOURCE_QR:
            adjustment.return_qr_count = 1 if amount > 0 else 0
            adjustment.return_qr_amount = amount
        else:
            adjustment.support_amount = amount
        if commit:
            adjustment.save()
        return adjustment
