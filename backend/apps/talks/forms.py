from django import forms
from django.db.models import Count

from apps.accounts.models import Member
from apps.talks.models import KnowledgeTag


class TalksLoginForm(forms.Form):
    login_id = forms.CharField(label="ID", max_length=64)
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "IDまたはパスワードが違います。",
    }

    member = None

    def clean(self):
        cleaned_data = super().clean()
        login_id = (cleaned_data.get("login_id") or "").strip()
        password = cleaned_data.get("password") or ""
        if not login_id or not password:
            return cleaned_data

        member = Member.objects.active().filter(login_id=login_id).first()
        if not member or member.password != password:
            raise forms.ValidationError(self.error_messages["invalid_login"])

        self.member = member
        return cleaned_data


class PostEditForm(forms.Form):
    title = forms.CharField(label="タイトル", max_length=255)
    body = forms.CharField(label="本文", widget=forms.Textarea)
    tags = forms.MultipleChoiceField(label="タグ", required=True, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tag_names = list(
            KnowledgeTag.objects.filter(is_active=True)
            .annotate(post_count=Count("posts")).order_by("-post_count", "name")
            .values_list("name", flat=True)
        )
        self.fields["tags"].choices = [(name, name) for name in tag_names]


class CommentEditForm(forms.Form):
    body = forms.CharField(label="コメント", widget=forms.Textarea)


class TagManageForm(forms.Form):
    tag_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(label="タグ名", max_length=64)
    is_active = forms.BooleanField(label="有効", required=False, initial=True)

    def clean_name(self):
        return (self.cleaned_data.get("name") or "").strip()
