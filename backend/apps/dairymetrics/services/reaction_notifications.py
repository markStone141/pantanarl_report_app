from django.utils import timezone

from apps.accounts.models import Member

from ..models import MemberMetricTransactionReaction, MemberMetricTransactionReactionNotificationState


def _unread_reaction_queryset(member: Member):
    state = getattr(member, "metric_transaction_reaction_notification_state", None)
    queryset = MemberMetricTransactionReaction.objects.filter(
        transaction__entry__member=member,
    ).exclude(member=member)
    if state and state.last_seen_at:
        queryset = queryset.filter(updated_at__gt=state.last_seen_at)
    return queryset


def unread_transaction_reaction_notification(*, member: Member, url: str = "", limit: int = 5) -> dict:
    if member is None:
        return {"count": 0, "url": url, "items": []}

    queryset = _unread_reaction_queryset(member)
    reaction_labels = dict(MemberMetricTransactionReaction.REACTION_CHOICES)
    items = []
    for reaction in queryset.select_related(
        "member",
        "transaction",
        "transaction__entry",
        "transaction__entry__department",
    ).order_by("-updated_at", "-id")[:limit]:
        transaction = reaction.transaction
        entry = transaction.entry
        items.append(
            {
                "member_name": reaction.member.name,
                "reaction_label": reaction_labels.get(reaction.reaction_type, reaction.reaction_type),
                "department_code": entry.department.code,
                "entry_date": entry.entry_date,
                "amount": int(transaction.support_amount or 0),
                "location": transaction.location,
            }
        )
    return {"count": queryset.count(), "url": url, "items": items}


def mark_transaction_reaction_notifications_seen(*, member: Member) -> None:
    if member is None:
        return
    MemberMetricTransactionReactionNotificationState.objects.update_or_create(
        member=member,
        defaults={"last_seen_at": timezone.now()},
    )
