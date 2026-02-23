from django.db import models


class Member(models.Model):
    name = models.CharField(max_length=64)
    login_id = models.CharField(max_length=64, unique=True)
    password = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.login_id})"
