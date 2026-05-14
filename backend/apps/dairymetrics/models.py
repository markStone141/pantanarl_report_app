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
    input_source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_ADMIN)
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

    @property
    def has_transactions(self) -> bool:
        return self.transactions.exists()

    def recalculate_from_transactions(self, *, save: bool = True) -> tuple[int, int]:
        totals = self.transactions.aggregate(
            total_count=models.Count("id"),
            total_amount=models.Sum("support_amount"),
        )
        self.result_count = int(totals["total_count"] or 0)
        self.support_amount = int(totals["total_amount"] or 0)
        if save:
            self.save(update_fields=["result_count", "support_amount", "updated_at"])
        return self.result_count, self.support_amount


class DepartmentDailyMetricSummary(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="daily_metric_summaries",
    )
    entry_date = models.DateField(default=timezone.localdate)
    approach_count = models.PositiveIntegerField(default=0)
    communication_count = models.PositiveIntegerField(default=0)
    result_count = models.PositiveIntegerField(default=0)
    support_amount = models.PositiveIntegerField(default=0)
    daily_target_count = models.PositiveIntegerField(default=0)
    daily_target_amount = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_department_daily_metric_summaries",
    )
    updated_by = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_department_daily_metric_summaries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-entry_date", "department__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "entry_date"],
                name="unique_department_daily_metric_summary",
            )
        ]

    def __str__(self) -> str:
        return f"{self.department.code} {self.entry_date}"

    def recalculate_from_entries(self, *, save: bool = True) -> tuple[int, int]:
        totals = MemberDailyMetricEntry.objects.filter(
            department=self.department,
            entry_date=self.entry_date,
        ).aggregate(
            total_approach=models.Sum("approach_count"),
            total_communication=models.Sum("communication_count"),
            total_count=models.Sum("result_count"),
            total_amount=models.Sum("support_amount"),
        )
        self.approach_count = int(totals["total_approach"] or 0)
        self.communication_count = int(totals["total_communication"] or 0)
        self.result_count = int(totals["total_count"] or 0)
        self.support_amount = int(totals["total_amount"] or 0)
        if save:
            self.save(
                update_fields=[
                    "approach_count",
                    "communication_count",
                    "result_count",
                    "support_amount",
                    "updated_at",
                ]
            )
        return self.result_count, self.support_amount


class MemberMetricTransaction(models.Model):
    AGE_BAND_TEENS = "teens"
    AGE_BAND_TWENTIES = "twenties"
    AGE_BAND_THIRTIES = "thirties"
    AGE_BAND_FORTIES = "forties"
    AGE_BAND_FIFTIES = "fifties"
    AGE_BAND_SIXTIES = "sixties"
    AGE_BAND_SEVENTIES = "seventies"
    AGE_BAND_EIGHTIES = "eighties"
    AGE_BAND_NINETIES_OR_OLDER = "nineties_or_older"
    AGE_BAND_CHOICES = [
        (AGE_BAND_TEENS, "10代"),
        (AGE_BAND_TWENTIES, "20代"),
        (AGE_BAND_THIRTIES, "30代"),
        (AGE_BAND_FORTIES, "40代"),
        (AGE_BAND_FIFTIES, "50代"),
        (AGE_BAND_SIXTIES, "60代"),
        (AGE_BAND_SEVENTIES, "70代"),
        (AGE_BAND_EIGHTIES, "80代"),
        (AGE_BAND_NINETIES_OR_OLDER, "90代以上"),
    ]
    GENDER_MALE = "male"
    GENDER_FEMALE = "female"
    GENDER_CHOICES = [
        (GENDER_MALE, "男性"),
        (GENDER_FEMALE, "女性"),
    ]
    NATIONALITY_DOMESTIC = "domestic"
    NATIONALITY_OVERSEAS = "overseas"
    NATIONALITY_CHOICES = [
        (NATIONALITY_DOMESTIC, "国内"),
        (NATIONALITY_OVERSEAS, "海外"),
    ]

    entry = models.ForeignKey(
        MemberDailyMetricEntry,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    support_amount = models.PositiveIntegerField(default=0)
    age_band = models.CharField(max_length=32, choices=AGE_BAND_CHOICES)
    is_student = models.BooleanField(default=False)
    gender = models.CharField(max_length=16, choices=GENDER_CHOICES)
    nationality_type = models.CharField(max_length=16, choices=NATIONALITY_CHOICES)
    location = models.CharField(max_length=128, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.entry} #{self.pk or 'new'}"


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
