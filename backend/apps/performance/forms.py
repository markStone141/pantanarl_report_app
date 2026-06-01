from django import forms
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.dairymetrics.forms import MemberDailyMetricEntryForm
from apps.dairymetrics.models import MemberMetricTransaction, MetricAdjustment


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


class PerformanceAdjustmentListFilterForm(forms.Form):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label="部署",
        empty_label="すべての部署",
    )
    q = forms.CharField(required=False, label="検索")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")


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
    UN_SOURCE_CHOICES = [
        (MetricAdjustment.SOURCE_POSTAL, "郵送"),
        (MetricAdjustment.SOURCE_QR, "QR"),
        (MetricAdjustment.SOURCE_INCREASE, "増額"),
    ]
    WV_SOURCE_CHOICES = [
        (MetricAdjustment.SOURCE_CS, "CS"),
        (MetricAdjustment.SOURCE_REFUGEE, "難民"),
        (MetricAdjustment.SOURCE_CS_PLUS_REFUGEE, "CS+難民"),
    ]
    AMOUNT_DIRECT = "direct"
    AMOUNT_CHOICES = [(str(value), f"{value:,}円") for value in range(500, 5001, 500)]
    AMOUNT_SELECT_CHOICES = [(AMOUNT_DIRECT, "直接入力")] + AMOUNT_CHOICES

    amount_choice = forms.ChoiceField(label="金額", choices=AMOUNT_SELECT_CHOICES, initial="500")
    amount = forms.IntegerField(label="金額を直接入力", min_value=0, required=False)

    class Meta:
        model = MetricAdjustment
        fields = [
            "department",
            "member",
            "target_date",
            "source_type",
            "location_name",
        ]
        widgets = {
            "target_date": forms.DateInput(attrs={"type": "date", "class": "dairymetrics-native-date dairymetrics-date-input"}),
        }

    @staticmethod
    def _is_wv_department(department):
        return bool(department and getattr(department, "code", "") == "WV")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("code")
        self.fields["department"].label = "部署"
        self.fields["member"].label = "メンバー"
        selected_department = self._resolve_department()
        is_wv_department = self._is_wv_department(selected_department)
        self.fields["source_type"] = forms.ChoiceField(
            label="種別",
            choices=self.WV_SOURCE_CHOICES if is_wv_department else self.UN_SOURCE_CHOICES,
        )
        member_queryset = Member.objects.active().filter(department_links__department__is_active=True).distinct()
        if selected_department is not None:
            member_queryset = member_queryset.filter(department_links__department=selected_department).distinct()
        else:
            member_queryset = member_queryset.none()
        self.fields["member"].queryset = member_queryset.order_by("name")
        self.fields["member"].empty_label = "メンバーを選択"
        self.fields["department"].empty_label = "部署を選択"
        self.fields["target_date"].label = "対象日"
        self.fields["location_name"].label = "現場"
        self.fields["location_name"].required = False
        if is_wv_department:
            self.fields["amount_choice"].label = "難民支援金額"
            self.fields["amount"].label = "難民支援金額を直接入力"
        self.fields["target_date"].initial = self.initial.get("target_date") or timezone.localdate()
        self.fields["amount"].widget.attrs.update({"inputmode": "numeric", "min": "0"})
        self.order_fields(["department", "member", "target_date", "source_type", "location_name", "amount_choice", "amount"])
        if self.instance and self.instance.pk:
            initial_amount = self._resolve_instance_amount(self.instance)
            self.fields["amount"].initial = initial_amount
            if str(initial_amount) in {choice[0] for choice in self.AMOUNT_CHOICES}:
                self.fields["amount_choice"].initial = str(initial_amount)
            else:
                self.fields["amount_choice"].initial = self.AMOUNT_DIRECT
            allowed_choices = self.WV_SOURCE_CHOICES if is_wv_department else self.UN_SOURCE_CHOICES
            if self.instance.source_type in {choice[0] for choice in allowed_choices}:
                self.fields["source_type"].initial = self.instance.source_type
            else:
                self.fields["source_type"].initial = (
                    MetricAdjustment.SOURCE_CS if is_wv_department else MetricAdjustment.SOURCE_INCREASE
                )
        elif not self.is_bound:
            self.fields["amount_choice"].initial = "500"
            self.fields["source_type"].initial = (
                MetricAdjustment.SOURCE_CS if is_wv_department else MetricAdjustment.SOURCE_INCREASE
            )

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
        if instance.source_type == MetricAdjustment.SOURCE_CS:
            return 0
        if instance.source_type == MetricAdjustment.SOURCE_CS_PLUS_REFUGEE:
            return max(int(instance.support_amount or 0) - MemberMetricTransaction.WV_CS_UNIT_AMOUNT, 0)
        if instance.source_type == MetricAdjustment.SOURCE_REFUGEE:
            return int(instance.support_amount or 0)
        if instance.source_type == MetricAdjustment.SOURCE_POSTAL:
            return int(instance.return_postal_amount or 0)
        if instance.source_type == MetricAdjustment.SOURCE_QR:
            return int(instance.return_qr_amount or 0)
        return int(instance.support_amount or 0)

    def clean(self):
        cleaned_data = super().clean()
        amount_choice = cleaned_data.get("amount_choice")
        direct_amount = cleaned_data.get("amount")
        source_type = cleaned_data.get("source_type")
        is_wv_department = self._is_wv_department(cleaned_data.get("department"))
        if is_wv_department and source_type == MetricAdjustment.SOURCE_CS:
            cleaned_data["resolved_amount"] = 0
        else:
            if amount_choice == self.AMOUNT_DIRECT:
                if direct_amount is None:
                    self.add_error("amount", "直接入力の金額を入れてください。")
                else:
                    cleaned_data["resolved_amount"] = int(direct_amount)
            elif amount_choice:
                cleaned_data["resolved_amount"] = int(amount_choice)
            else:
                self.add_error("amount_choice", "金額を選択してください。")
            if is_wv_department and source_type in {
                MetricAdjustment.SOURCE_REFUGEE,
                MetricAdjustment.SOURCE_CS_PLUS_REFUGEE,
            } and int(cleaned_data.get("resolved_amount") or 0) <= 0:
                self.add_error("amount_choice", "難民支援金額を入力してください。")
        return cleaned_data

    def save(self, commit=True):
        adjustment = super().save(commit=False)
        amount = int(self.cleaned_data.get("resolved_amount") or 0)
        source_type = self.cleaned_data["source_type"]
        is_wv_department = self._is_wv_department(adjustment.department)
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
        if is_wv_department:
            if source_type == MetricAdjustment.SOURCE_CS:
                adjustment.result_count = 1
                adjustment.support_amount = MemberMetricTransaction.WV_CS_UNIT_AMOUNT
                adjustment.cs_count = 1
            elif source_type == MetricAdjustment.SOURCE_REFUGEE:
                adjustment.result_count = 1 if amount > 0 else 0
                adjustment.support_amount = amount
                adjustment.refugee_count = 1 if amount > 0 else 0
            elif source_type == MetricAdjustment.SOURCE_CS_PLUS_REFUGEE:
                adjustment.result_count = 2 if amount > 0 else 1
                adjustment.support_amount = MemberMetricTransaction.WV_CS_UNIT_AMOUNT + amount
                adjustment.cs_count = 1
                adjustment.refugee_count = 1 if amount > 0 else 0
        elif source_type == MetricAdjustment.SOURCE_POSTAL:
            adjustment.return_postal_count = 1 if amount > 0 else 0
            adjustment.return_postal_amount = amount
        elif source_type == MetricAdjustment.SOURCE_QR:
            adjustment.return_qr_count = 1 if amount > 0 else 0
            adjustment.return_qr_amount = amount
        else:
            adjustment.result_count = 1 if amount > 0 else 0
            adjustment.support_amount = amount
        if commit:
            adjustment.save()
        return adjustment
