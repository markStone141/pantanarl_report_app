from django.utils import timezone

from apps.dairymetrics.models import MemberDailyMetricEntry


def auto_close_stale_entries(*, today=None) -> int:
    today = today or timezone.localdate()
    stale_entries = MemberDailyMetricEntry.objects.filter(
        activity_closed=False,
        entry_date__lt=today,
    )
    closed_at = timezone.now()
    updated = stale_entries.update(
        activity_closed=True,
        activity_closed_at=closed_at,
    )
    return updated
