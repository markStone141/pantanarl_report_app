from django.db import models
from django.utils import timezone

from apps.accounts.models import Department, Member


class DailyDepartmentReport(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="daily_reports",
    )
    report_date = models.DateField(default=timezone.localdate)
    reporter = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_reports",
    )
    total_count = models.PositiveIntegerField(default=0)
    followup_count = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=128, blank=True)
    memo = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-report_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.department.code} {self.report_date}"


class DailyDepartmentReportLine(models.Model):
    report = models.ForeignKey(
        DailyDepartmentReport,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_report_lines",
    )
    amount = models.PositiveIntegerField(default=0)
    count = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
