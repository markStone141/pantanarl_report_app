from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.accounts.models import Department, Member
from apps.targets.models import Period


class MemberDailyMetricEntry(models.Model):
    SOURCE_MEMBER = "member"
    SOURCE_ADMIN = "admin"
    SOURCE_CHOICES = [
        (SOURCE_MEMBER, "本人入力"),
        (SOURCE_ADMIN, "管理者編集"),
    ]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="metric_entries")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="metric_entries")
    entry_date = models.DateField(default=timezone.localdate)
    approach_count = models.PositiveIntegerField(default=0)
    communication_count = models.PositiveIntegerField(default=0)
    result_count = models.PositiveIntegerField(default=0)
    support_amount = models.PositiveIntegerField(default=0)
    daily_target_count = models.PositiveIntegerField(default=0)
    daily_target_amount = models.PositiveIntegerField(default=0)
    cs_count = models.PositiveIntegerField(default=0)
    refugee_count = models.PositiveIntegerField(default=0)
    location_name = models.CharField(max_length=128, blank=True)
    memo = models.TextField(blank=True)
    activity_closed = models.BooleanField(default=False)
    activity_closed_at = models.DateTimeField(null=True, blank=True)
    synced_to_report = models.BooleanField(default=False)
    input_source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-entry_date", "member__name", "department__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "department", "entry_date"],
                name="unique_member_department_entry_date",
            )
        ]

    def __str__(self) -> str:
        return f"{self.member.name} {self.department.code} {self.entry_date}"


class MetricAdjustment(models.Model):
    SOURCE_POSTAL = "postal"
    SOURCE_INCREASE = "increase"
    SOURCE_OTHER = "other"
    SOURCE_CHOICES = [
        (SOURCE_POSTAL, "郵送"),
        (SOURCE_INCREASE, "増額"),
        (SOURCE_OTHER, "その他"),
    ]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="metric_adjustments")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="metric_adjustments")
    target_date = models.DateField(default=timezone.localdate)
    source_type = models.CharField(max_length=24, choices=SOURCE_CHOICES, default=SOURCE_OTHER)
    approach_count = models.PositiveIntegerField(default=0)
    communication_count = models.PositiveIntegerField(default=0)
    result_count = models.PositiveIntegerField(default=0)
    support_amount = models.PositiveIntegerField(default=0)
    return_postal_count = models.PositiveIntegerField(default=0)
    return_postal_amount = models.PositiveIntegerField(default=0)
    return_qr_count = models.PositiveIntegerField(default=0)
    return_qr_amount = models.PositiveIntegerField(default=0)
    cs_count = models.PositiveIntegerField(default=0)
    refugee_count = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_metric_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-target_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.member.name} {self.department.code} {self.target_date} {self.source_type}"


class MemberPeriodMetricTarget(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="period_metric_targets")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="member_period_metric_targets")
    period = models.ForeignKey(Period, on_delete=models.CASCADE, related_name="member_metric_targets")
    target_count = models.PositiveIntegerField(default=0)
    target_amount = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period__start_date", "member__name", "department__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "department", "period"],
                name="unique_member_department_period_target",
            )
        ]

    def __str__(self) -> str:
        return f"{self.member.name} {self.department.code} {self.period.name}"


class MemberMonthMetricTarget(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="month_metric_targets")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="member_month_metric_targets")
    target_month = models.DateField()
    target_count = models.PositiveIntegerField(default=0)
    target_amount = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-target_month", "member__name", "department__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "department", "target_month"],
                name="unique_member_department_month_target",
            )
        ]

    def __str__(self) -> str:
        return f"{self.member.name} {self.department.code} {self.target_month:%Y-%m}"
