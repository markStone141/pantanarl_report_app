from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from apps.testimony.models import Article, ArticleViewHistory


def unread_recent_article_notification(*, user, days: int = 14) -> dict:
    if not user or not user.is_authenticated:
        return {"count": 0, "url": reverse("testimony_article_list")}

    since = timezone.now() - timedelta(days=days)
    viewed = ArticleViewHistory.objects.filter(user=user, article_id=OuterRef("pk"))
    queryset = (
        Article.objects.filter(created_at__gte=since)
        .annotate(has_viewed=Exists(viewed))
        .filter(has_viewed=False)
    )
    count = queryset.count()
    return {
        "count": count,
        "url": reverse("testimony_article_list"),
    }
