from django.db import models

from apps.accounts.models import Department


class Period(models.Model):
    month = models.DateField()
    name = models.CharField(max_length=64)
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
