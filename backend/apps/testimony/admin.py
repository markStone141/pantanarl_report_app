from django.contrib import admin

from .models import Article, ArticleFavorite, ArticleLike, ArticleViewHistory, Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "legacy_product_id", "created_at")
    search_fields = ("name",)


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "author", "product", "view_count", "legacy_article_id")
    list_filter = ("product",)
    search_fields = ("title", "author", "body")


@admin.register(ArticleFavorite)
class ArticleFavoriteAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "article", "created_at")


@admin.register(ArticleLike)
class ArticleLikeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "article", "created_at")


@admin.register(ArticleViewHistory)
class ArticleViewHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "article", "view_count", "last_viewed_at")
