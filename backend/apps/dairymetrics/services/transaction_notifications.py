from django.utils import timezone

from apps.accounts.models import Member

from ..models import (
    MemberMetricTransaction,
    MemberMetricTransactionNotificationState,
)
from .entry_context import member_departments


def _today_transaction_queryset(member: Member, *, today, unread_only: bool = False):
    state = getattr(member, "metric_transaction_notification_state", None)
    department_ids = list(member_departments(member).values_list("id", flat=True))
    queryset = MemberMetricTransaction.objects.filter(
        entry__entry_date=today,
        entry__department_id__in=department_ids,
    ).exclude(entry__member=member)
    if unread_only and state and state.last_seen_at:
        queryset = queryset.filter(created_at__gt=state.last_seen_at)
    return queryset


def unread_today_transaction_notification(*, member: Member, url: str = "", today=None) -> dict:
    if member is None:
        return {"count": 0, "url": url, "items": []}

    today = today or timezone.localdate()
    queryset = _today_transaction_queryset(member, today=today, unread_only=True)
    return {
        "count": queryset.count(),
        "url": url,
        "items": [],
    }


def mark_today_transaction_notifications_seen(*, member: Member) -> None:
    if member is None:
        return
    MemberMetricTransactionNotificationState.objects.update_or_create(
        member=member,
        defaults={"last_seen_at": timezone.now()},
    )
