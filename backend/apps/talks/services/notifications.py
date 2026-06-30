from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from apps.talks.models import KnowledgePost, KnowledgePostRead


def unread_recent_post_notification(*, user, days: int = 14) -> dict:
    url = f"{reverse('talks_index')}?unread=1"
    if not user or not user.is_authenticated:
        return {"count": 0, "url": url}

    since = timezone.now() - timedelta(days=days)
    current_read = KnowledgePostRead.objects.filter(
        user=user,
        post_id=OuterRef("pk"),
        read_at__gte=OuterRef("updated_at"),
    )
    count = (
        KnowledgePost.objects.filter(
            status=KnowledgePost.Status.PUBLISHED,
            is_deleted=False,
            updated_at__gte=since,
        )
        .annotate(has_current_read=Exists(current_read))
        .filter(has_current_read=False)
        .count()
    )
    return {"count": count, "url": url}
