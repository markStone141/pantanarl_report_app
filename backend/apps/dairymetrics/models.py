from django.conf import settings
from django.db import models, transaction
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
    daily_target_cs_count = models.PositiveIntegerField(default=0)
    daily_target_refugee_count = models.PositiveIntegerField(default=0)
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
        transactions = list(
            self.transactions.only("support_amount", "wv_result_type", "wv_cs_count", "wv_refugee_amount")
        )
        self.support_amount = sum(int(tx.support_amount or 0) for tx in transactions)
        if self.department.code == "WV":
            self.cs_count = sum(
                MemberMetricTransaction._wv_effective_cs_count(
                    result_type=tx.wv_result_type,
                    cs_count=tx.wv_cs_count,
                )
                for tx in transactions
            )
            self.refugee_count = sum(
                MemberMetricTransaction._wv_effective_refugee_count(
                    result_type=tx.wv_result_type,
                    refugee_amount=tx.wv_refugee_amount,
                )
                for tx in transactions
            )
            self.result_count = self.cs_count + self.refugee_count
        else:
            self.result_count = len(transactions)
        if save:
            update_fields = ["result_count", "support_amount", "updated_at"]
            if self.department.code == "WV":
                update_fields.extend(["cs_count", "refugee_count"])
            self.save(update_fields=update_fields)
        return self.result_count, self.support_amount

    def apply_transaction_delta(
        self,
        *,
        count_delta: int = 0,
        amount_delta: int = 0,
        cs_delta: int = 0,
        refugee_delta: int = 0,
        save: bool = True,
    ) -> tuple[int, int]:
        self.result_count = max(int(self.result_count or 0) + int(count_delta or 0), 0)
        self.support_amount = max(int(self.support_amount or 0) + int(amount_delta or 0), 0)
        if self.department.code == "WV":
            self.cs_count = max(int(self.cs_count or 0) + int(cs_delta or 0), 0)
            self.refugee_count = max(int(self.refugee_count or 0) + int(refugee_delta or 0), 0)
        if save:
            update_fields = ["result_count", "support_amount", "updated_at"]
            if self.department.code == "WV":
                update_fields.extend(["cs_count", "refugee_count"])
            self.save(update_fields=update_fields)
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

    @classmethod
    def get_or_create_for_entry(cls, *, entry):
        summary, created = cls.objects.get_or_create(
            department=entry.department,
            entry_date=entry.entry_date,
            defaults={
                "created_by": entry.member,
                "updated_by": entry.member,
            },
        )
        if not created and summary.updated_by_id is None:
            summary.updated_by = entry.member
            summary.save(update_fields=["updated_by", "updated_at"])
        return summary

    def apply_transaction_delta(
        self,
        *,
        count_delta: int = 0,
        amount_delta: int = 0,
        updated_by=None,
        save: bool = True,
    ) -> tuple[int, int]:
        self.result_count = max(int(self.result_count or 0) + int(count_delta or 0), 0)
        self.support_amount = max(int(self.support_amount or 0) + int(amount_delta or 0), 0)
        if updated_by is not None:
            self.updated_by = updated_by
        if save:
            update_fields = ["result_count", "support_amount", "updated_at"]
            if updated_by is not None:
                update_fields.append("updated_by")
            self.save(update_fields=update_fields)
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
    WV_RESULT_CS = "cs"
    WV_RESULT_REFUGEE = "refugee"
    WV_RESULT_BOTH = "both"
    WV_RESULT_TYPE_CHOICES = [
        (WV_RESULT_CS, "CSのみ"),
        (WV_RESULT_REFUGEE, "難民のみ"),
        (WV_RESULT_BOTH, "両方"),
    ]
    WV_CS_UNIT_AMOUNT = 4500

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
    wv_result_type = models.CharField(max_length=16, choices=WV_RESULT_TYPE_CHOICES, blank=True)
    wv_cs_count = models.PositiveIntegerField(default=0)
    wv_refugee_amount = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=128, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.entry} #{self.pk or 'new'}"

    @staticmethod
    def _wv_effective_cs_count(*, result_type, cs_count):
        if result_type not in {MemberMetricTransaction.WV_RESULT_CS, MemberMetricTransaction.WV_RESULT_BOTH}:
            return 0
        return int(cs_count or 0) or 1

    @staticmethod
    def _wv_effective_refugee_count(*, result_type, refugee_amount):
        if result_type in {MemberMetricTransaction.WV_RESULT_REFUGEE, MemberMetricTransaction.WV_RESULT_BOTH}:
            return 1 if int(refugee_amount or 0) > 0 else 0
        return 0

    @classmethod
    def _wv_count_deltas(cls, *, entry, result_type, cs_count, refugee_amount, delta_sign):
        if entry.department.code != "WV":
            return delta_sign, 0, 0
        cs_delta = cls._wv_effective_cs_count(result_type=result_type, cs_count=cs_count) * delta_sign
        refugee_delta = cls._wv_effective_refugee_count(
            result_type=result_type,
            refugee_amount=refugee_amount,
        ) * delta_sign
        return cs_delta + refugee_delta, cs_delta, refugee_delta

    def _normalize_wv_fields(self):
        if self.entry.department.code != "WV":
            self.wv_result_type = ""
            self.wv_cs_count = 0
            self.wv_refugee_amount = 0
            return
        original_amount = int(self.support_amount or 0)
        cs_count = int(self.wv_cs_count or 0)
        refugee_amount = int(self.wv_refugee_amount or 0)
        if not self.wv_result_type:
            if cs_count > 0 and refugee_amount > 0:
                self.wv_result_type = self.WV_RESULT_BOTH
            elif cs_count > 0:
                self.wv_result_type = self.WV_RESULT_CS
            else:
                self.wv_result_type = self.WV_RESULT_REFUGEE
                if refugee_amount <= 0:
                    refugee_amount = original_amount
        if self.wv_result_type == self.WV_RESULT_CS:
            refugee_amount = 0
            cs_count = cs_count or 1
        elif self.wv_result_type == self.WV_RESULT_REFUGEE:
            cs_count = 0
        elif self.wv_result_type == self.WV_RESULT_BOTH:
            cs_count = cs_count or 1
        self.wv_cs_count = cs_count
        self.wv_refugee_amount = refugee_amount
        self.support_amount = (self.wv_cs_count * self.WV_CS_UNIT_AMOUNT) + self.wv_refugee_amount

    @classmethod
    def _apply_entry_delta(cls, *, entry, amount_delta, result_type, cs_count, refugee_amount, delta_sign):
        count_delta, cs_delta, refugee_delta = cls._wv_count_deltas(
            entry=entry,
            result_type=result_type,
            cs_count=cs_count,
            refugee_amount=refugee_amount,
            delta_sign=delta_sign,
        )
        entry.apply_transaction_delta(
            count_delta=count_delta,
            amount_delta=amount_delta,
            cs_delta=cs_delta,
            refugee_delta=refugee_delta,
        )
        summary = DepartmentDailyMetricSummary.get_or_create_for_entry(entry=entry)
        summary.apply_transaction_delta(
            count_delta=count_delta,
            amount_delta=amount_delta,
            updated_by=entry.member,
        )

    def save(self, *args, **kwargs):
        old_entry_id = None
        old_support_amount = 0
        old_result_type = ""
        old_cs_count = 0
        old_refugee_amount = 0
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).select_related("entry", "entry__member", "entry__department").first()
            if previous:
                old_entry_id = previous.entry_id
                old_support_amount = int(previous.support_amount or 0)
                old_result_type = previous.wv_result_type or ""
                old_cs_count = int(previous.wv_cs_count or 0)
                old_refugee_amount = int(previous.wv_refugee_amount or 0)

        with transaction.atomic():
            self._normalize_wv_fields()
            super().save(*args, **kwargs)
            new_support_amount = int(self.support_amount or 0)
            new_result_type = self.wv_result_type or ""
            new_cs_count = int(self.wv_cs_count or 0)
            new_refugee_amount = int(self.wv_refugee_amount or 0)
            if old_entry_id is None:
                self._apply_entry_delta(
                    entry=self.entry,
                    amount_delta=new_support_amount,
                    result_type=new_result_type,
                    cs_count=new_cs_count,
                    refugee_amount=new_refugee_amount,
                    delta_sign=1,
                )
                return

            if old_entry_id == self.entry_id:
                amount_delta = new_support_amount - old_support_amount
                if (
                    amount_delta
                    or old_result_type != new_result_type
                    or old_cs_count != new_cs_count
                    or old_refugee_amount != new_refugee_amount
                ):
                    old_count_delta, old_cs_delta, old_refugee_delta = self._wv_count_deltas(
                        entry=self.entry,
                        result_type=old_result_type,
                        cs_count=old_cs_count,
                        refugee_amount=old_refugee_amount,
                        delta_sign=-1,
                    )
                    new_count_delta, new_cs_delta, new_refugee_delta = self._wv_count_deltas(
                        entry=self.entry,
                        result_type=new_result_type,
                        cs_count=new_cs_count,
                        refugee_amount=new_refugee_amount,
                        delta_sign=1,
                    )
                    self.entry.apply_transaction_delta(
                        count_delta=old_count_delta + new_count_delta,
                        amount_delta=amount_delta,
                        cs_delta=old_cs_delta + new_cs_delta,
                        refugee_delta=old_refugee_delta + new_refugee_delta,
                    )
                    if amount_delta or old_count_delta + new_count_delta:
                        summary = DepartmentDailyMetricSummary.get_or_create_for_entry(entry=self.entry)
                        summary.apply_transaction_delta(
                            count_delta=old_count_delta + new_count_delta,
                            amount_delta=amount_delta,
                            updated_by=self.entry.member,
                        )
                return

            old_entry = MemberDailyMetricEntry.objects.select_related("member", "department").get(pk=old_entry_id)
            self._apply_entry_delta(
                entry=old_entry,
                amount_delta=-old_support_amount,
                result_type=old_result_type,
                cs_count=old_cs_count,
                refugee_amount=old_refugee_amount,
                delta_sign=-1,
            )
            self._apply_entry_delta(
                entry=self.entry,
                amount_delta=new_support_amount,
                result_type=new_result_type,
                cs_count=new_cs_count,
                refugee_amount=new_refugee_amount,
                delta_sign=1,
            )

    def delete(self, *args, **kwargs):
        entry = self.entry
        support_amount = int(self.support_amount or 0)
        result_type = self.wv_result_type or ""
        cs_count = int(self.wv_cs_count or 0)
        refugee_amount = int(self.wv_refugee_amount or 0)
        with transaction.atomic():
            super().delete(*args, **kwargs)
            self._apply_entry_delta(
                entry=entry,
                amount_delta=-support_amount,
                result_type=result_type,
                cs_count=cs_count,
                refugee_amount=refugee_amount,
                delta_sign=-1,
            )


class MetricAdjustment(models.Model):
    SOURCE_POSTAL = "postal"
    SOURCE_QR = "qr"
    SOURCE_INCREASE = "increase"
    SOURCE_OTHER = "other"
    SOURCE_CHOICES = [
        (SOURCE_POSTAL, "郵送"),
        (SOURCE_QR, "QR"),
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
    location_name = models.CharField(max_length=120, blank=True)
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
