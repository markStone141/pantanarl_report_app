from django.db import models
from django.utils import timezone

from apps.accounts.models import Department, Member


class MailIntegrationSetting(models.Model):
    PROVIDER_GMAIL = "gmail"
    PROVIDER_CHOICES = [
        (PROVIDER_GMAIL, "Gmail"),
    ]

    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_GMAIL)
    sender_email = models.EmailField(blank=True)
    sender_name = models.CharField(max_length=128, blank=True)
    client_id = models.CharField(max_length=255, blank=True)
    client_secret = models.CharField(max_length=255, blank=True)
    refresh_token = models.TextField(blank=True)
    token_uri = models.URLField(default="https://oauth2.googleapis.com/token")
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.get_provider_display()}連携設定"


class MailRecipientGroup(models.Model):
    name = models.CharField(max_length=128, unique=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mail_recipient_groups",
    )
    related_departments = models.ManyToManyField(
        Department,
        blank=True,
        related_name="mail_recipient_group_links",
    )
    is_active = models.BooleanField(default=True)
    members = models.ManyToManyField(
        Member,
        through="MailRecipientGroupMember",
        related_name="mail_recipient_groups",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class MailRecipientGroupMember(models.Model):
    group = models.ForeignKey(
        MailRecipientGroup,
        on_delete=models.CASCADE,
        related_name="group_memberships",
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="mail_group_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "member"],
                name="unique_mail_group_member",
            )
        ]
        ordering = ["group__name", "member__name", "id"]

    def __str__(self) -> str:
        return f"{self.group.name} -> {self.member.name}"


class MailSendHistory(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "準備中"),
        (STATUS_SENT, "送信済み"),
        (STATUS_FAILED, "失敗"),
    ]

    integration_setting = models.ForeignKey(
        MailIntegrationSetting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="send_histories",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mail_send_histories",
    )
    activity_date = models.DateField(default=timezone.localdate)
    sender_member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_mail_histories",
    )
    transaction = models.ForeignKey(
        "dairymetrics.MemberMetricTransaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mail_send_histories",
    )
    recipient_group = models.ForeignKey(
        MailRecipientGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="send_histories",
    )
    subject_snapshot = models.CharField(max_length=255)
    body_snapshot = models.TextField(blank=True)
    sent_to_snapshot = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_test = models.BooleanField(default=False)
    is_resend = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-activity_date", "-sent_at", "-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.activity_date} {self.subject_snapshot}"


class MailDepartmentRouting(models.Model):
    department = models.OneToOneField(
        Department,
        on_delete=models.CASCADE,
        related_name="mail_routing",
    )
    recipient_group = models.ForeignKey(
        MailRecipientGroup,
        on_delete=models.CASCADE,
        related_name="department_routings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department__code", "id"]

    def __str__(self) -> str:
        return f"{self.department.code} -> {self.recipient_group.name}"
