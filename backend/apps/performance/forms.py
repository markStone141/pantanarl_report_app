from django import forms
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.dairymetrics.forms import MemberDailyMetricEntryForm

from .forms_adjustments import (
    PerformanceAdjustmentListFilterForm,
    PerformanceMetricAdjustmentForm,
)


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


class PerformanceAdminEntryFilterForm(forms.Form):
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
        self.fields["member"].queryset = Member.objects.order_by("name")
        if not self.is_bound:
            today = timezone.localdate()
            self.initial.setdefault("date_to", today)
            self.initial.setdefault("date_from", today.replace(day=1))


class PerformancePastEntrySelectionForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=True,
        label="部署",
        empty_label="部署を選択",
    )
    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        required=True,
        label="メンバー",
        empty_label="メンバーを選択",
    )
    entry_date = forms.DateField(
        required=True,
        label="日付",
        widget=forms.DateInput(attrs={"type": "date", "class": "dairymetrics-native-date dairymetrics-date-input"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")
        selected_department = self._resolve_department()
        member_queryset = Member.objects.filter(department_links__department__is_active=True).distinct()
        if selected_department is not None:
            member_queryset = member_queryset.filter(department_links__department=selected_department).distinct()
        else:
            member_queryset = member_queryset.none()
        self.fields["member"].queryset = member_queryset.order_by("name")
        if not self.is_bound:
            self.initial.setdefault("entry_date", timezone.localdate())

    def _resolve_department(self):
        department_id = None
        if self.is_bound:
            department_id = self.data.get(self.add_prefix("department")) or self.data.get("department")
        else:
            initial_department = self.initial.get("department")
            if isinstance(initial_department, Department):
                return initial_department
            department_id = initial_department
        if department_id:
            return Department.objects.filter(pk=department_id, is_active=True).first()
        return None

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get("department")
        member = cleaned_data.get("member")
        if department and member:
            belongs = member.default_department_id == department.id or member.department_links.filter(department=department).exists()
            if not belongs:
                self.add_error("member", "選択した部署に所属するメンバーを選択してください。")
        return cleaned_data


class PerformancePastEntryCreateForm(forms.Form):
    location_name = forms.CharField(label="現場名", max_length=128, required=False)
    approach_count = forms.IntegerField(label="アプローチ", min_value=0, initial=0, required=False)
    communication_count = forms.IntegerField(label="コミュニケーション", min_value=0, initial=0, required=False)

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["approach_count"] = cleaned_data.get("approach_count") or 0
        cleaned_data["communication_count"] = cleaned_data.get("communication_count") or 0
        return cleaned_data


class PerformanceMemberDailyMetricEntryForm(MemberDailyMetricEntryForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, member=None, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")
        if self.instance and self.instance.pk and self.instance.has_transactions:
            for field_name in ("result_count", "support_amount"):
                if field_name in self.fields:
                    self.fields[field_name].disabled = True
                    self.fields[field_name].help_text = "決済明細から自動計算されます。"
