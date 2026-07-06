from django import forms
from django.contrib.auth import authenticate
from django.utils import timezone

from apps.accounts.models import Department, Member

from .models import (
    DepartmentDailyMetricSummary,
    MemberDailyMetricEntry,
    MemberMetricTransaction,
    MemberMonthMetricTarget,
    MemberPeriodMetricTarget,
    MetricAdjustment,
)


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
            "entry_date": forms.DateInput(attrs={"type": "date", "class": "dairymetrics-native-date dairymetrics-date-input"}),
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
            "target_date": forms.DateInput(attrs={"type": "date", "class": "dairymetrics-native-date dairymetrics-date-input"}),
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
    target_cs_count = forms.IntegerField(label="目標 CS件数", min_value=0, required=False, initial=0)
    target_refugee_count = forms.IntegerField(label="目標 難民件数", min_value=0, required=False, initial=0)
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
        self.department_code = department.code if department is not None else self.initial.get("department_code", "")

        if department is not None:
            self.initial.setdefault("department", department)
        if scope == "period":
            self.fields["period_name"] = forms.CharField(label="対象路程", required=False, disabled=True)
            self.order_fields(["department", "period_name", "target_count", "target_cs_count", "target_refugee_count", "target_amount"])
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
            self.order_fields(["department", "target_month_label", "target_count", "target_cs_count", "target_refugee_count", "target_amount"])
            self.initial.setdefault("target_month_label", self.target_month.strftime("%Y/%m"))
            if member and department:
                self.target_instance = MemberMonthMetricTarget.objects.filter(
                    member=member,
                    department=department,
                    target_month=self.target_month,
                ).first()

        if self.target_instance:
            self.initial.setdefault("target_count", self.target_instance.target_count)
            self.initial.setdefault("target_cs_count", getattr(self.target_instance, "target_cs_count", 0))
            self.initial.setdefault("target_refugee_count", getattr(self.target_instance, "target_refugee_count", 0))
            self.initial.setdefault("target_amount", self.target_instance.target_amount)

        department_code = self._resolve_department_code()
        if department_code == "WV":
            self.fields.pop("target_count", None)
        else:
            self.fields.pop("target_cs_count", None)
            self.fields.pop("target_refugee_count", None)

    def _resolve_department_code(self):
        if self.is_bound:
            department_id = self.data.get(self.add_prefix("department")) or self.data.get("department")
            if department_id:
                department = Department.objects.filter(pk=department_id).only("code").first()
                if department is not None:
                    return department.code
        initial_department = self.initial.get("department")
        if isinstance(initial_department, Department):
            return initial_department.code
        if self.department_code:
            return self.department_code
        return ""

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get("department")
        department_code = department.code if department is not None else self._resolve_department_code()
        cleaned_data["target_count"] = cleaned_data.get("target_count") or 0
        cleaned_data["target_cs_count"] = cleaned_data.get("target_cs_count") or 0
        cleaned_data["target_refugee_count"] = cleaned_data.get("target_refugee_count") or 0
        cleaned_data["target_amount"] = cleaned_data.get("target_amount") or 0
        if department_code == "WV":
            cleaned_data["target_count"] = cleaned_data["target_cs_count"] + cleaned_data["target_refugee_count"]
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
        if hasattr(instance, "target_cs_count"):
            instance.target_cs_count = self.cleaned_data.get("target_cs_count") or 0
        if hasattr(instance, "target_refugee_count"):
            instance.target_refugee_count = self.cleaned_data.get("target_refugee_count") or 0
        instance.target_amount = self.cleaned_data["target_amount"]
        instance.save()
        return instance


class DairymetricsV2PersonalSetupForm(forms.Form):
    department = forms.ModelChoiceField(queryset=Department.objects.none(), label="部署")
    entry_date = forms.DateField(
        label="活動日",
        widget=forms.DateInput(attrs={"type": "date", "class": "dairymetrics-native-date dairymetrics-date-input"}),
    )
    location_name = forms.CharField(label="今日の活動現場", max_length=128, required=False)
    daily_target_count = forms.IntegerField(label="個人の件数目標", min_value=0, initial=0)
    daily_target_cs_count = forms.IntegerField(label="個人のCS件数目標", min_value=0, initial=0, required=False)
    daily_target_refugee_count = forms.IntegerField(label="個人の難民件数目標", min_value=0, initial=0, required=False)
    daily_target_amount = forms.IntegerField(label="個人の金額目標", min_value=0, initial=0)

    def __init__(self, *args, member=None, **kwargs):
        super().__init__(*args, **kwargs)
        departments = Department.objects.filter(is_active=True)
        if member is not None:
            departments = departments.filter(member_links__member=member).distinct()
        self.fields["department"].queryset = departments.order_by("code")
        department_code = self._resolve_department_code()
        if department_code == "WV":
            self.fields["daily_target_count"].required = False
        else:
            self.fields.pop("daily_target_cs_count", None)
            self.fields.pop("daily_target_refugee_count", None)

    def _resolve_department_code(self):
        if self.is_bound:
            department = self.data.get(self.add_prefix("department")) or self.data.get("department")
            if department and str(department).isdigit():
                department_obj = self.fields["department"].queryset.filter(pk=department).first()
                return department_obj.code if department_obj else ""
        initial_department = self.initial.get("department")
        if hasattr(initial_department, "code"):
            return initial_department.code
        return ""

    def clean(self):
        cleaned_data = super().clean()
        if self._resolve_department_code() == "WV":
            cleaned_data["daily_target_cs_count"] = cleaned_data.get("daily_target_cs_count") or 0
            cleaned_data["daily_target_refugee_count"] = cleaned_data.get("daily_target_refugee_count") or 0
            cleaned_data["daily_target_count"] = (
                cleaned_data["daily_target_cs_count"] + cleaned_data["daily_target_refugee_count"]
            )
        return cleaned_data


class DairymetricsV2DepartmentTargetForm(forms.ModelForm):
    class Meta:
        model = DepartmentDailyMetricSummary
        fields = ["entry_date", "daily_target_amount"]
        widgets = {
            "entry_date": forms.DateInput(attrs={"type": "date", "class": "dairymetrics-native-date dairymetrics-date-input"}),
        }
        labels = {
            "entry_date": "全体目標の対象日",
            "daily_target_amount": "全体目標金額",
        }

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.department = department
        self.fields["daily_target_amount"].min_value = 0


class DairymetricsV2TransactionForm(forms.ModelForm):
    class Meta:
        model = MemberMetricTransaction
        fields = [
            "support_amount",
            "wv_result_type",
            "wv_cs_count",
            "wv_refugee_amount",
            "location",
            "age_band",
            "is_student",
            "gender",
            "nationality_type",
            "comment",
        ]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {
            "support_amount": "決済金額",
            "wv_result_type": "決済区分",
            "wv_cs_count": "CS口数",
            "wv_refugee_amount": "難民支援金額",
            "location": "場所",
            "age_band": "年代",
            "is_student": "学生",
            "gender": "性別",
            "nationality_type": "国籍分類",
            "comment": "コメント",
        }

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.department = department
        self.fields["support_amount"].min_value = 0
        if not department or department.code != "WV":
            self.fields["wv_result_type"].required = False
            self.fields["wv_cs_count"].required = False
            self.fields["wv_refugee_amount"].required = False
            self.fields["wv_result_type"].widget = forms.HiddenInput()
            self.fields["wv_cs_count"].widget = forms.HiddenInput()
            self.fields["wv_refugee_amount"].widget = forms.HiddenInput()
            self.fields["wv_result_type"].initial = ""
            self.fields["wv_cs_count"].initial = 0
            self.fields["wv_refugee_amount"].initial = 0
        else:
            self.fields["support_amount"].required = False
            self.fields["wv_result_type"].required = True
            self.fields["wv_result_type"].initial = self.initial.get(
                "wv_result_type",
                MemberMetricTransaction.WV_RESULT_CS,
            )
            self.fields["wv_cs_count"].required = False
            self.fields["wv_refugee_amount"].required = False
            self.fields["wv_cs_count"].min_value = 0
            self.fields["wv_refugee_amount"].min_value = 0

    def clean(self):
        cleaned_data = super().clean()
        age_band = cleaned_data.get("age_band")
        if age_band not in {
            MemberMetricTransaction.AGE_BAND_TEENS,
            MemberMetricTransaction.AGE_BAND_TWENTIES,
        }:
            cleaned_data["is_student"] = False
        if self.department and self.department.code == "WV":
            result_type = cleaned_data.get("wv_result_type")
            cs_count = cleaned_data.get("wv_cs_count") or 0
            refugee_amount = cleaned_data.get("wv_refugee_amount") or 0
            if not result_type:
                self.add_error("wv_result_type", "区分を選択してください。")
            if result_type in {
                MemberMetricTransaction.WV_RESULT_CS,
                MemberMetricTransaction.WV_RESULT_BOTH,
            } and cs_count <= 0:
                self.add_error("wv_cs_count", "CS口数を入力してください。")
            if result_type in {
                MemberMetricTransaction.WV_RESULT_REFUGEE,
                MemberMetricTransaction.WV_RESULT_BOTH,
            } and refugee_amount <= 0:
                self.add_error("wv_refugee_amount", "難民支援金額を入力してください。")
            if result_type == MemberMetricTransaction.WV_RESULT_REFUGEE:
                cleaned_data["wv_cs_count"] = 0
            if result_type == MemberMetricTransaction.WV_RESULT_CS:
                cleaned_data["wv_refugee_amount"] = 0
            cleaned_data["support_amount"] = (
                (cleaned_data.get("wv_cs_count") or 0) * MemberMetricTransaction.WV_CS_UNIT_AMOUNT
                + (cleaned_data.get("wv_refugee_amount") or 0)
            )
        else:
            cleaned_data["wv_result_type"] = ""
            cleaned_data["wv_cs_count"] = 0
            cleaned_data["wv_refugee_amount"] = 0
        return cleaned_data


class DairymetricsV2CloseoutForm(forms.ModelForm):
    class Meta:
        model = MemberDailyMetricEntry
        fields = ["approach_count", "communication_count", "memo"]
        labels = {
            "approach_count": "アプローチ",
            "communication_count": "コミュニケーション",
            "memo": (
                "活動中に感じた「あのときこうすればよかったのでは」「ここが足りなかった」"
                "「あの時どうすればよかったんだろう」などといった悔しい気持ちを入力してください（任意）"
            ),
        }
        widgets = {
            "memo": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": (
                        "印象に残った状況やトーク、決めきれなかった理由、"
                        "次に試したいことなどを自由に記入してください。"
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("approach_count", "communication_count"):
            self.fields[field_name].min_value = 0
            self.fields[field_name].required = False
            self.fields[field_name].initial = self.initial.get(field_name, 0)
        self.fields["memo"].required = False

    def clean(self):
        cleaned_data = super().clean()
        for field_name in ("approach_count", "communication_count"):
            if cleaned_data.get(field_name) in {None, ""}:
                cleaned_data[field_name] = 0
        return cleaned_data
