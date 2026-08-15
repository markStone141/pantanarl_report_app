import re
import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.models import Department


_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_site_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return _WHITESPACE_PATTERN.sub(" ", normalized).strip().casefold()


class ActivitySite(models.Model):
    canonical_name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    departments = models.ManyToManyField(
        Department,
        through="ActivitySiteDepartment",
        related_name="activity_sites",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_activity_sites",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_activity_sites",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["canonical_name", "id"]
        indexes = [models.Index(fields=["is_active", "canonical_name"], name="site_active_name_idx")]

    def save(self, *args, **kwargs):
        self.canonical_name = str(self.canonical_name or "").strip()
        self.normalized_name = normalize_site_name(self.canonical_name)
        if not self.normalized_name:
            raise ValidationError({"canonical_name": "現場名を入力してください。"})
        if ActivitySiteAlias.objects.filter(normalized_name=self.normalized_name).exists():
            raise ValidationError({"canonical_name": "この名称は別の現場の別名として登録済みです。"})
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"canonical_name", "normalized_name"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.canonical_name


class ActivitySiteDepartment(models.Model):
    site = models.ForeignKey(ActivitySite, on_delete=models.CASCADE, related_name="department_links")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="activity_site_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["department__code", "site__canonical_name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "department"], name="unique_activity_site_department")
        ]

    def __str__(self) -> str:
        return f"{self.site.canonical_name} -> {self.department.code}"


class ActivitySiteAlias(models.Model):
    SOURCE_IMPORT = "import"
    SOURCE_PROPOSAL = "proposal"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_IMPORT, "過去データ取込"),
        (SOURCE_PROPOSAL, "新規現場申請"),
        (SOURCE_MANUAL, "管理者登録"),
    ]

    site = models.ForeignKey(ActivitySite, on_delete=models.CASCADE, related_name="aliases")
    alias_name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128, unique=True, editable=False)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["alias_name", "id"]

    def save(self, *args, **kwargs):
        self.alias_name = str(self.alias_name or "").strip()
        self.normalized_name = normalize_site_name(self.alias_name)
        if not self.normalized_name:
            raise ValidationError({"alias_name": "別名を入力してください。"})
        if ActivitySite.objects.filter(normalized_name=self.normalized_name).exists():
            raise ValidationError({"alias_name": "この名称は正式な現場名として登録済みです。"})
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"alias_name", "normalized_name"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.alias_name} -> {self.site.canonical_name}"


class ActivitySiteProposal(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_MERGED = "merged"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "申請中"),
        (STATUS_APPROVED, "承認済み"),
        (STATUS_MERGED, "既存現場へ統合"),
        (STATUS_REJECTED, "却下"),
    ]

    proposed_name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128, editable=False)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="activity_site_proposals")
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_site_proposals",
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    resolved_site = models.ForeignKey(
        ActivitySite,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_proposals",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_activity_site_proposals",
    )
    review_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "normalized_name"],
                condition=Q(status="pending"),
                name="unique_pending_site_proposal",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["pending", "rejected"]) | Q(resolved_site__isnull=False),
                name="resolved_site_required_after_approval",
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="site_prop_status_idx")]

    def clean(self):
        super().clean()
        if self.status in {self.STATUS_APPROVED, self.STATUS_MERGED} and self.resolved_site_id is None:
            raise ValidationError({"resolved_site": "承認・統合時は正式な現場を選択してください。"})

    def save(self, *args, **kwargs):
        self.proposed_name = str(self.proposed_name or "").strip()
        self.normalized_name = normalize_site_name(self.proposed_name)
        if not self.normalized_name:
            raise ValidationError({"proposed_name": "申請する現場名を入力してください。"})
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"proposed_name", "normalized_name"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.proposed_name} ({self.get_status_display()})"
