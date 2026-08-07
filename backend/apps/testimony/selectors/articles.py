from __future__ import annotations

from datetime import timedelta

from django.db.models import BooleanField, Case, Count, Exists, F, OuterRef, Q, Value, When
from django.http import HttpRequest
from django.utils import timezone

from ..models import Article, ArticleViewHistory, Product


TESTIMONY_SORT_OPTIONS = [
    ("latest", "新着順"),
    ("testimonied_at", "証日"),
    ("favorites", "お気に入りが多い順"),
    ("likes", "いいねが多い順"),
    ("views", "閲覧数順"),
]


def new_article_cutoff():
    return timezone.now() - timedelta(days=7)


def testimony_article_queryset(request: HttpRequest):
    sort = request.GET.get("sort", "latest")
    keyword = (request.GET.get("q") or "").strip()
    product_id = (request.GET.get("product") or "").strip()
    viewed = ArticleViewHistory.objects.filter(user=request.user, article_id=OuterRef("pk"))
    queryset = (
        Article.objects.select_related("product", "created_by")
        .annotate(favorite_count=Count("favorites", distinct=True), like_count=Count("likes", distinct=True))
        .annotate(has_viewed_by_user=Exists(viewed))
    )
    queryset = queryset.annotate(
        is_new_for_user=Case(
            When(created_at__gte=new_article_cutoff(), has_viewed_by_user=False, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )
    )
    if keyword:
        queryset = queryset.filter(Q(title__icontains=keyword) | Q(body__icontains=keyword) | Q(author__icontains=keyword))
    if product_id.isdigit():
        queryset = queryset.filter(product_id=int(product_id))

    if sort == "views":
        return queryset.order_by("-view_count", "-updated_at", "-id")
    if sort == "favorites":
        return queryset.order_by("-favorite_count", "-updated_at", "-id")
    if sort == "likes":
        return queryset.order_by("-like_count", "-updated_at", "-id")
    if sort == "testimonied_at":
        return queryset.order_by(F("testimonied_at").desc(nulls_last=True), "-created_at", "-id")
    return queryset.order_by("-created_at", "-id")


def testimony_filter_context(request: HttpRequest) -> dict:
    selected_sort = request.GET.get("sort", "latest")
    if selected_sort not in {value for value, _ in TESTIMONY_SORT_OPTIONS}:
        selected_sort = "latest"
    return {
        "q": (request.GET.get("q") or "").strip(),
        "selected_sort": selected_sort,
        "selected_product": (request.GET.get("product") or "").strip(),
        "products": Product.objects.order_by("name", "id"),
        "sort_options": TESTIMONY_SORT_OPTIONS,
    }
