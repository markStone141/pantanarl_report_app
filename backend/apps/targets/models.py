from django.db import models

from apps.accounts.models import Department

TARGET_STATUS_ACTIVE = "active"
TARGET_STATUS_PLANNED = "planned"
TARGET_STATUS_FINISHED = "finished"
TARGET_STATUS_CHOICES = [
    (TARGET_STATUS_ACTIVE, "active"),
    (TARGET_STATUS_PLANNED, "planned"),
    (TARGET_STATUS_FINISHED, "finished"),
]


class Period(models.Model):
    month = models.DateField()
    name = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=TARGET_STATUS_CHOICES, default=TARGET_STATUS_PLANNED)
    start_date = models.DateField()
    end_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-month", "start_date", "id"]
        unique_together = ("month", "name")

    def __str__(self) -> str:
        return f"{self.name} ({self.start_date} - {self.end_date})"


class DepartmentMonthTarget(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="month_targets",
    )
    target_month = models.DateField()
    target_count = models.PositiveIntegerField(default=0)
    target_amount = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-target_month", "department__code"]
        unique_together = ("department", "target_month")


class DepartmentPeriodTarget(models.Model):
    period = models.ForeignKey(
        Period,
        on_delete=models.CASCADE,
        related_name="department_targets",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="period_targets",
    )
    target_count = models.PositiveIntegerField(default=0)
    target_amount = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["period__month", "department__code"]
        unique_together = ("period", "department")


class TargetMetric(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="target_metrics",
    )
    code = models.CharField(max_length=32)
    label = models.CharField(max_length=64)
    unit = models.CharField(max_length=16, blank=True)
    display_order = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department__code", "display_order", "id"]
        unique_together = ("department", "code")


class MonthTargetMetricValue(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="month_metric_values",
    )
    target_month = models.DateField()
    metric = models.ForeignKey(
        TargetMetric,
        on_delete=models.CASCADE,
        related_name="month_values",
    )
    status = models.CharField(max_length=16, choices=TARGET_STATUS_CHOICES, default=TARGET_STATUS_PLANNED)
    value = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-target_month", "department__code", "metric__display_order", "id"]
        unique_together = ("department", "target_month", "metric")


class PeriodTargetMetricValue(models.Model):
    period = models.ForeignKey(
        Period,
        on_delete=models.CASCADE,
        related_name="metric_values",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="period_metric_values",
    )
    metric = models.ForeignKey(
        TargetMetric,
        on_delete=models.CASCADE,
        related_name="period_values",
    )
    value = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["period__month", "department__code", "metric__display_order", "id"]
        unique_together = ("period", "department", "metric")
