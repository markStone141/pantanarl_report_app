from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class KnowledgeTag(models.Model):
    name = models.CharField(max_length=64, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class KnowledgeReactionType(models.Model):
    code = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=64)
    icon_class = models.CharField(max_length=128, default="fa-solid fa-circle")
    color = models.CharField(max_length=16, default="#126e82")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.label} ({self.code})"


class KnowledgePost(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        PUBLISHED = "published", "公開"
        ARCHIVED = "archived", "アーカイブ"

    title = models.CharField(max_length=255)
    body = models.TextField()
    author_member = models.ForeignKey(
        "accounts.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="knowledge_posts",
    )
    author_name_snapshot = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PUBLISHED)
    is_deleted = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tags = models.ManyToManyField("KnowledgeTag", through="KnowledgePostTag", related_name="posts")

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-updated_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return self.title


class KnowledgePostTag(models.Model):
    post = models.ForeignKey(KnowledgePost, on_delete=models.CASCADE, related_name="post_tags")
    tag = models.ForeignKey(KnowledgeTag, on_delete=models.CASCADE, related_name="tag_posts")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "tag")
        indexes = [
            models.Index(fields=["tag", "post"]),
        ]

    def __str__(self) -> str:
        return f"{self.post_id}:{self.tag_id}"


class KnowledgeComment(models.Model):
    post = models.ForeignKey(KnowledgePost, on_delete=models.CASCADE, related_name="comments")
    author_member = models.ForeignKey(
        "accounts.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="knowledge_comments",
    )
    author_name_snapshot = models.CharField(max_length=64, blank=True)
    body = models.TextField()
    reaction_type = models.ForeignKey(
        KnowledgeReactionType,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["post", "created_at"]),
            models.Index(fields=["post", "reaction_type", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(id=models.F("parent")),
                name="knowledge_comment_parent_not_self",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.parent_id and self.parent and self.parent.parent_id:
            raise ValidationError("返信は1段階までです。")

    def __str__(self) -> str:
        return f"{self.post_id}:{self.id}"


class KnowledgeUserPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="knowledge_preference",
    )
    preferred_tags = models.ManyToManyField(
        KnowledgeTag,
        blank=True,
        related_name="preferred_by_users",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Preference<{self.user_id}>"
