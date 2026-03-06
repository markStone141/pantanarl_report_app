from django.conf import settings
from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    legacy_product_id = models.BigIntegerField(null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Article(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="testimony_articles",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    author = models.CharField(max_length=255)
    video_url = models.URLField(blank=True)
    testimonied_at = models.DateField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    legacy_article_id = models.BigIntegerField(null=True, blank=True, unique=True)
    migrated_at = models.DateTimeField(null=True, blank=True)
    migration_source = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["testimonied_at"]),
            models.Index(fields=["product"]),
        ]

    def __str__(self) -> str:
        return self.title


class ArticleFavorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="testimony_favorites")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="favorites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "article"], name="testimony_unique_favorite"),
        ]


class ArticleLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="testimony_likes")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "article"], name="testimony_unique_like"),
        ]


class ArticleViewHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="testimony_view_histories")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="view_histories")
    first_viewed_at = models.DateTimeField()
    last_viewed_at = models.DateTimeField()
    view_count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "article"], name="testimony_unique_view_history"),
        ]
        indexes = [
            models.Index(fields=["user", "-last_viewed_at"]),
        ]
