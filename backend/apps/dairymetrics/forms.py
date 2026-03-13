from django import forms
from django.contrib.auth import authenticate
from django.utils import timezone

from apps.accounts.models import Department, Member

from .models import MemberDailyMetricEntry, MemberMonthMetricTarget, MemberPeriodMetricTarget, MetricAdjustment


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
    LABELS = {
        "department": "部署",
        "entry_date": "日付",
        "approach_count": "アプローチ",
        "communication_count": "コミュニケーション",
        "result_count": "件数",
        "support_amount": "支援金額",
        "daily_target_count": "今日の目標 件数",
        "daily_target_amount": "今日の目標 金額",
        "cs_count": "CS",
        "refugee_count": "難民",
        "location_name": "現場名",
        "memo": "メモ",
    }

    class Meta:
        model = MemberDailyMetricEntry
        fields = [
            "department",
            "entry_date",
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "daily_target_count",
            "daily_target_amount",
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
        for name, label in self.LABELS.items():
            if name in self.fields:
                self.fields[name].label = label
        for name in [
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "daily_target_count",
            "daily_target_amount",
            "cs_count",
            "refugee_count",
        ]:
            self.fields[name].min_value = 0
            self.fields[name].required = False
            self.fields[name].initial = 0
        department_code = self._resolve_department_code()
        if department_code == "WV":
            self.fields.pop("result_count", None)
        else:
            self.fields.pop("cs_count", None)
            self.fields.pop("refugee_count", None)
        self.order_fields([
            "department",
            "entry_date",
            "daily_target_count",
            "daily_target_amount",
            "approach_count",
            "communication_count",
            "result_count",
            "cs_count",
            "refugee_count",
            "support_amount",
            "location_name",
            "memo",
        ])

    def _resolve_department_code(self):
        department = None
        if self.is_bound:
            department = self.data.get(self.add_prefix("department")) or self.data.get("department")
        if not department:
            initial_department = self.initial.get("department")
            if hasattr(initial_department, "code"):
                return initial_department.code
            department = initial_department
        if not department and self.instance and getattr(self.instance, "department_id", None):
            return self.instance.department.code
        if not department:
            return ""
        if isinstance(department, str) and not department.isdigit():
            return department
        department_obj = self.fields["department"].queryset.filter(pk=department).first()
        return department_obj.code if department_obj else ""

    def clean(self):
        cleaned_data = super().clean()
        for name in [
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "daily_target_count",
            "daily_target_amount",
            "cs_count",
            "refugee_count",
        ]:
            if name in self.fields and cleaned_data.get(name) in {None, ""}:
                cleaned_data[name] = 0
        return cleaned_data


class MetricAdjustmentForm(forms.ModelForm):
    LABELS = {
        "member": "メンバー",
        "department": "部署",
        "target_date": "対象日",
        "source_type": "種別",
        "approach_count": "アプローチ",
        "communication_count": "コミュニケーション",
        "result_count": "件数",
        "support_amount": "金額",
        "return_postal_count": "郵送件数",
        "return_postal_amount": "郵送金額",
        "return_qr_count": "QR件数",
        "return_qr_amount": "QR金額",
        "cs_count": "CS",
        "refugee_count": "難民",
        "note": "メモ",
    }

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
            "return_postal_count",
            "return_postal_amount",
            "return_qr_count",
            "return_qr_amount",
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
        for name, label in self.LABELS.items():
            if name in self.fields:
                self.fields[name].label = label
        for name in [
            "approach_count",
            "communication_count",
            "result_count",
            "support_amount",
            "return_postal_count",
            "return_postal_amount",
            "return_qr_count",
            "return_qr_amount",
            "cs_count",
            "refugee_count",
        ]:
            self.fields[name].min_value = 0
            self.fields[name].required = False
            self.fields[name].initial = 0


class MemberScopeTargetForm(forms.Form):
    department = forms.ModelChoiceField(queryset=Department.objects.none(), label="部署")
    target_count = forms.IntegerField(label="目標 件数", min_value=0, required=False, initial=0)
    target_amount = forms.IntegerField(label="目標 金額", min_value=0, required=False, initial=0)

    def __init__(self, *args, member=None, scope="month", department=None, period=None, target_month=None, **kwargs):
        super().__init__(*args, **kwargs)
        departments = Department.objects.filter(is_active=True)
        if member is not None:
            departments = departments.filter(member_links__member=member).distinct()
        self.fields["department"].queryset = departments.order_by("code")
        self.member = member
        self.scope = scope
        self.period = period
        self.target_month = target_month or timezone.localdate().replace(day=1)
        self.target_instance = None

        if department is not None:
            self.initial.setdefault("department", department)
        if scope == "period":
            self.fields["period_name"] = forms.CharField(label="対象路程", required=False, disabled=True)
            self.order_fields(["department", "period_name", "target_count", "target_amount"])
            if period is not None:
                self.initial.setdefault("period_name", period.name)
                if member and department:
                    self.target_instance = MemberPeriodMetricTarget.objects.filter(
                        member=member,
                        department=department,
                        period=period,
                    ).first()
        else:
            self.fields["target_month_label"] = forms.CharField(label="対象月", required=False, disabled=True)
            self.order_fields(["department", "target_month_label", "target_count", "target_amount"])
            self.initial.setdefault("target_month_label", self.target_month.strftime("%Y/%m"))
            if member and department:
                self.target_instance = MemberMonthMetricTarget.objects.filter(
                    member=member,
                    department=department,
                    target_month=self.target_month,
                ).first()

        if self.target_instance:
            self.initial.setdefault("target_count", self.target_instance.target_count)
            self.initial.setdefault("target_amount", self.target_instance.target_amount)

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["target_count"] = cleaned_data.get("target_count") or 0
        cleaned_data["target_amount"] = cleaned_data.get("target_amount") or 0
        return cleaned_data

    def save(self):
        department = self.cleaned_data["department"]
        if self.scope == "period":
            instance = self.target_instance or MemberPeriodMetricTarget(
                member=self.member,
                department=department,
                period=self.period,
            )
        else:
            instance = self.target_instance or MemberMonthMetricTarget(
                member=self.member,
                department=department,
                target_month=self.target_month,
            )
        instance.member = self.member
        instance.department = department
        instance.target_count = self.cleaned_data["target_count"]
        instance.target_amount = self.cleaned_data["target_amount"]
        instance.save()
        return instance
