from django.db import models
from django.conf import settings


class MemberQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def create(self, **kwargs):
        # Backward compatibility: ignore legacy plaintext password argument.
        kwargs.pop("password", None)
        return super().create(**kwargs)


class Department(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    default_reporter = models.ForeignKey(
        "Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_department_links",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Member(models.Model):
    name = models.CharField(max_length=64)
    login_id = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="member_profile",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = MemberQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.login_id})"


class MemberDepartment(models.Model):
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="department_links",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="member_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("member", "department")

    def __str__(self) -> str:
        return f"{self.member.login_id} -> {self.department.code}"
