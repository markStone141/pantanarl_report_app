from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.accounts.models import Department, Member


class MemberDailyMetricEntry(models.Model):
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
    synced_to_report = models.BooleanField(default=False)
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
