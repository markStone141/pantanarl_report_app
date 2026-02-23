from django.db import models


class Department(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Member(models.Model):
    name = models.CharField(max_length=64)
    login_id = models.CharField(max_length=64, unique=True)
    password = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

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
