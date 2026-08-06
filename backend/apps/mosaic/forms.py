from django import forms

from apps.accounts.models import Member

from .models import MosaicInteraction, MosaicResultType, MosaicTrialModel, MosaicVisitPurpose


AGE_BAND_CHOICES = [
    ("", "選択なし"),
    ("10代", "10代"),
    ("20代", "20代"),
    ("30代", "30代"),
    ("40代", "40代"),
    ("50代", "50代"),
    ("60代", "60代"),
    ("70代", "70代"),
    ("80代以上", "80代以上"),
]


class MosaicInteractionForm(forms.ModelForm):
    class Meta:
        model = MosaicInteraction
        fields = [
            "interaction_date",
            "input_member",
            "service_member",
            "credited_member",
            "age_band",
            "party_type",
            "visit_purpose",
            "stay_duration_minutes",
            "trial_model",
            "needs",
            "talk_summary",
            "result",
            "payment_amount",
            "is_return_support",
            "memo",
        ]
        widgets = {
            "interaction_date": forms.DateInput(attrs={"type": "date"}),
            "age_band": forms.Select(choices=AGE_BAND_CHOICES),
            "needs": forms.Textarea(attrs={"rows": 3}),
            "talk_summary": forms.Textarea(attrs={"rows": 4}),
            "memo": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_members = Member.objects.active().order_by("name")
        self.fields["input_member"].queryset = active_members
        self.fields["service_member"].queryset = active_members
        self.fields["credited_member"].queryset = active_members
        self.fields["visit_purpose"].queryset = MosaicVisitPurpose.objects.active()
        self.fields["trial_model"].queryset = MosaicTrialModel.objects.active()
        self.fields["result"].queryset = MosaicResultType.objects.active()
        self.fields["input_member"].required = True
        self.fields["service_member"].required = True
        self.fields["credited_member"].required = False
        self.fields["payment_amount"].min_value = 0


class MosaicVisitPurposeForm(forms.ModelForm):
    class Meta:
        model = MosaicVisitPurpose
        fields = ["name", "sort_order", "is_active"]


class MosaicTrialModelForm(forms.ModelForm):
    class Meta:
        model = MosaicTrialModel
        fields = ["name", "sort_order", "is_active"]


class MosaicResultTypeForm(forms.ModelForm):
    class Meta:
        model = MosaicResultType
        fields = ["name", "is_success", "sort_order", "is_active"]
