from django import forms

from apps.accounts.models import Member


class ReportSubmissionForm(forms.Form):
    report_date = forms.DateField(
        label="報告日",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reporter = forms.ModelChoiceField(
        label="責任者",
        queryset=Member.objects.none(),
        required=False,
        empty_label="選択してください",
    )
    memo = forms.CharField(
        label="全体メモ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, members=None, **kwargs):
        super().__init__(*args, **kwargs)
        if members is None:
            members = Member.objects.none()
        self.fields["reporter"].queryset = members
        self.fields["reporter"].label_from_instance = lambda member: member.name
